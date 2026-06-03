"""PayPal 自动/人工绑定执行器。"""

from __future__ import annotations

import json
import logging
import re
import secrets
import string
import threading
import time
import uuid
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from autoteam.auth_session_store import load_auth_session
from autoteam.bind_executor import _build_result, _capture_screenshot
from autoteam.chatgpt_api import ChatGPTTeamAPI
from autoteam.config import normalize_proxy_url
from autoteam.gopay_executor import (
    DEFAULT_STRIPE_PK,
    DEFAULT_STRIPE_RUNTIME_VERSION,
    STRIPE_API,
    STRIPE_VERSION_FULL,
    GoPayOTPCancelled,
    _accept_checkout_terms_on_page,
    _browser_checkout_nonzero_amount_hint,
    _dismiss_address_autocomplete,
    _extract_checkout_error,
    _extract_checkout_session_id,
    _inject_chatgpt_browser_cookies,
    _new_http_session,
    _open_checkout_in_page,
    _poll_otp_from_sms_url,
    _safe_proxy_summary,
    _safe_url_summary,
    _select_chatgpt_account_if_needed,
    _stripe_runtime_from_env,
    _suppress_address_autocomplete_ui,
)
from autoteam.paypal_protocol_signup import run_paypal_no_card_protocol_signup

logger = logging.getLogger(__name__)
DEFAULT_PAYPAL_NAME = "James Smith"
PAYPAL_ADDRESS_GENERATOR_URL = "https://www.meiguodizhi.com/api/v1/dz"
PAYPAL_ADDRESS_GENERATOR_REFERER = "https://www.meiguodizhi.com/"
_TUNNEL_ERROR_HINTS = (
    "err_tunnel_connection_failed",
    "tunnel connection failed",
)
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
DEFAULT_PAYPAL_JP_BILLING_PROFILE = {
    "name": DEFAULT_PAYPAL_NAME,
    "country": "JP",
    "state": "Tokyo",
    "city": "Chiyoda",
    "zip": "100-0001",
    "address1": "1-1 Chiyoda",
    "address2": "",
    "phone_number": "090-1234-5678",
}
DEFAULT_PAYPAL_JP_BIRTH_DATE = "1985/01/15"
DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME = "太郎"
DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME = "山田"
DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES = {
    "JP": DEFAULT_PAYPAL_JP_BILLING_PROFILE,
}
PAYPAL_COUNTRY_DEFAULT_LANG = {
    "US": "en",
    "JP": "ja",
}
US_STATE_NAME_TO_CODE = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
US_STATE_CODE_TO_NAME = {code: name for name, code in US_STATE_NAME_TO_CODE.items()}
JP_PREFECTURE_NAME_TO_JA = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "tokyo-to": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "kyoto-fu": "京都府",
    "osaka": "大阪府",
    "osaka-fu": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}
PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS = 120
PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS = 120
PAYPAL_SIGNUP_OTP_RESEND_AFTER_SECONDS = 60
PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS = 1
PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS = 120
PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS = 30
PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS = 180
PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS = 300
PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS = 120
PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS = 180
PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS = 120
PAYPAL_APPROVE_RETURN_SETTLE_SECONDS = 1.0
PAYPAL_ROXYBROWSER_FAILURE_KEEPALIVE_SECONDS = 60
PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS = 5.0
PAYPAL_OTP_PHONE_LOCK_TIMEOUT_SECONDS = 120
PAYPAL_SSL_PROTOCOL_ERROR_REFRESH_INTERVAL_SECONDS = 10
PAYPAL_SSL_PROTOCOL_ERROR_MAX_REFRESHES = 2
_PAYPAL_OTP_LOCK_GUARD = threading.Lock()
_PAYPAL_OTP_LOCKS: dict[str, threading.Lock] = {}


def _is_tunnel_connection_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(hint in text for hint in _TUNNEL_ERROR_HINTS)

SUCCESS_HINTS = (
    "payment successful",
    "payment complete",
    "thanks for subscribing",
    "subscription active",
    "subscription confirmed",
    "you are now subscribed",
    "your payment method was added",
    "you've successfully subscribed",
    "付款成功",
    "支付成功",
    "订阅成功",
)
PAYPAL_ACCOUNT_LIMITED_HINTS = (
    "your account is limited",
    "account is limited",
    "account limited",
    "paypal account overview",
    "resolve this problem",
    "账户受限",
    "账号受限",
)
PAYPAL_PHONE_REJECTED_HINTS = (
    "try a different phone number",
    "use a different phone number",
    "unable to complete your request",
    "we're unable to complete your request",
    "we’re unable to complete your request",
    "リクエストを完了できません",
    "リクエストを完了できませんでした",
    "別の電話番号",
    "別の電話番号をお試しください",
    "换一个手机号",
    "更换手机号",
)
PAYPAL_CARD_REJECTED_HINTS = (
    "this card has already been added to another paypal account",
    "card has already been added to another paypal account",
    "remove the card from the other account",
    "try a different way to pay",
    "use a different card",
    "try a different card",
    "card is already linked",
    "card already linked",
)
PAYPAL_CARD_LINKED_HINTS = (
    "this card has already been added to another paypal account",
    "card has already been added to another paypal account",
    "remove the card from the other account",
    "cc_linked_to_full_account",
    "card is already linked",
    "card already linked",
)
PAYPAL_CARD_CANDIDATE_REJECTED_HINTS = (
    "create_card_account_candidate_validation_error",
    "create card account candidate validation error",
    "candidate validation error",
)
PAYPAL_FUNDING_REJECTED_HINTS = (
    "instrument_sharing_limit_exceeded",
    "card_generic_error",
    "issuer_decline",
    "funding source was declined",
    "payment source was declined",
    "try a different way to pay",
)
PAYPAL_DATADOME_BLOCKED_HINTS = (
    "datadome",
    "captcha_failed",
    "slider_timeout",
    "event_name=slider_timeout",
    "blocked by datadome",
    "you have been blocked",
    "have been blocked",
    "your request has been blocked",
    "access to this page has been denied",
)
PAYPAL_HUMAN_VERIFICATION_HINTS = (
    "confirm you're human",
    "confirm you’re human",
    "move the slider all the way to the right",
    "security challenge",
    "security check",
    "human verification",
    "unusual activity",
    "人机验证",
    "安全验证",
)
PAYPAL_PHONE_REJECTED_SELECTORS = [
    '[role="dialog"]:has-text("Try a different phone number")',
    '[aria-modal="true"]:has-text("Try a different phone number")',
    'text="Try a different phone number"',
    'text="We’re unable to complete your request"',
    "text=\"We're unable to complete your request\"",
    'text="別の電話番号をお試しください"',
    'text="リクエストを完了できませんでした"',
]
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
AUTOFILL_FAST_SELECTORS = {
    # 只放高确定性的 checkout 字段，避免 broad selector 写到错误输入框后误判成功。
    "country": [
        'select[autocomplete="billing country"]',
        'select[autocomplete="country"]',
    ],
    "name": [
        'input[autocomplete="name"]',
        'input[autocomplete="cc-name"]',
    ],
    "email": [
        'input[autocomplete="email"]',
        'input[type="email"]',
    ],
    "phone": [
        'input[autocomplete="tel"]',
        'input[type="tel"]',
    ],
    "address1": [
        'input[autocomplete="billing address-line1"]',
        'input[autocomplete="address-line1"]',
        '#billingAddressLine1',
    ],
    "address2": [
        'input[autocomplete="billing address-line2"]',
        'input[autocomplete="address-line2"]',
        '#billingAddressLine2',
    ],
    "city": [
        'input[autocomplete="billing address-level2"]',
        'input[autocomplete="address-level2"]',
        '#billingLocality',
    ],
    "state": [
        'select[autocomplete="billing address-level1"]',
        'input[autocomplete="billing address-level1"]',
        'select[autocomplete="address-level1"]',
        'input[autocomplete="address-level1"]',
        '#billingAdministrativeArea',
    ],
    "postal_code": [
        'input[autocomplete="billing postal-code"]',
        'input[autocomplete="postal-code"]',
        '#billingPostalCode',
    ],
}

PAYPAL_EMAIL_SELECTORS = [
    'input#email',
    'input[name="login_email"]',
    'input[name="email"]',
    'input[type="email"]',
    'input[autocomplete="username"]',
    'input[placeholder*="email" i]',
    'input[aria-label*="email" i]',
]
PAYPAL_PASSWORD_SELECTORS = [
    'input#password',
    'input#password-field',
    'input[name="login_password"]',
    'input[name="password"]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
    'input[placeholder*="password" i]',
    'input[aria-label*="password" i]',
]
PAYPAL_BIRTH_DATE_SELECTORS = [
    'input[placeholder*="年/月/日"]',
    'input[aria-label*="生年月日"]',
    'input[placeholder*="生年月日"]',
    'input[name*="birth" i]',
    'input[id*="birth" i]',
    'input[name*="dob" i]',
    'input[id*="dob" i]',
    'input[autocomplete="bday"]',
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
PAYPAL_SIGNUP_EMAIL_SUBMIT_SELECTORS = [
    'button:has-text("Continue to Payment")',
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'button:has-text("Create Account")',
    'button:has-text("Create an Account")',
    'button:has-text("Sign Up")',
    'button:has-text("注册")',
    'button:has-text("创建账户")',
    'button:has-text("建立账户")',
    'button:has-text("建立帳戶")',
    'input[type="submit"]',
    '#btnNext',
    '#createAccount',
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
    "input#phoneNumber",
    'input[name="phone"]',
    'input[name="phoneNumber"]',
    'input[autocomplete="tel"]',
    'input[placeholder*="phone" i]',
    'input[aria-label*="phone" i]',
    'input[placeholder*="電話"]',
    'input[aria-label*="電話"]',
    'input[placeholder*="携帯"]',
    'input[aria-label*="携帯"]',
    'input[id*="phone" i]',
    'input[name*="phone" i]',
    'input[id*="tel" i]',
    'input[name*="tel" i]',
]
PAYPAL_CARD_NUMBER_SELECTORS = [
    "input#cardNumber",
    "input#card_number",
    "input#cc",
    'input[name="cardNumber"]',
    'input[name="card_number"]',
    'input[name="cc"]',
    'input[autocomplete="cc-number"]',
    'input[placeholder*="card number" i]',
    'input[aria-label*="card number" i]',
    'input[id*="card" i]',
    'input[name*="card" i]',
]
PAYPAL_CARD_EXPIRY_SELECTORS = [
    "input#cardExpiry",
    "input#expiryDate",
    'input[name="cardExpiry"]',
    'input[name="expiryDate"]',
    'input[autocomplete="cc-exp"]',
    'input[placeholder*="expiration" i]',
    'input[aria-label*="expiration" i]',
    'input[id*="expir" i]',
    'input[name*="expir" i]',
]
PAYPAL_CARD_CVV_SELECTORS = [
    "input#cardCvv",
    "input#cvv",
    "input#csc",
    'input[name="cardCvv"]',
    'input[name="cvv"]',
    'input[name="csc"]',
    'input[autocomplete="cc-csc"]',
    'input[placeholder*="cvv" i]',
    'input[aria-label*="cvv" i]',
    'input[id*="cvv" i]',
    'input[name*="cvv" i]',
]
PAYPAL_FIRST_NAME_SELECTORS = [
    "input#firstName",
    'input[name="firstName"]',
    'input[autocomplete="given-name"]',
    'input[placeholder*="first name" i]',
    'input[aria-label*="first name" i]',
]
PAYPAL_LAST_NAME_SELECTORS = [
    "input#lastName",
    'input[name="lastName"]',
    'input[autocomplete="family-name"]',
    'input[placeholder*="last name" i]',
    'input[aria-label*="last name" i]',
]
PAYPAL_BILLING_LINE1_SELECTORS = [
    "input#billingLine1",
    "input#address1",
    "input#streetAddress",
    'input[name="billingLine1"]',
    'input[name="address1"]',
    'input[name="streetAddress"]',
    'input[autocomplete="address-line1"]',
    'input[placeholder*="street address" i]',
    'input[aria-label*="street address" i]',
]
PAYPAL_BILLING_CITY_SELECTORS = [
    "input#billingCity",
    "input#city",
    'input[name="billingCity"]',
    'input[name="city"]',
    'input[autocomplete="address-level2"]',
    'input[placeholder*="city" i]',
    'input[aria-label*="city" i]',
]
PAYPAL_BILLING_POSTAL_SELECTORS = [
    "input#billingPostalCode",
    "input#zip",
    "input#postalCode",
    'input[name="billingPostalCode"]',
    'input[name="zip"]',
    'input[name="postalCode"]',
    'input[autocomplete="postal-code"]',
    'input[placeholder*="zip" i]',
    'input[aria-label*="zip" i]',
    'input[placeholder*="postal" i]',
    'input[aria-label*="postal" i]',
]
PAYPAL_BILLING_STATE_SELECTORS = [
    "select#billingState",
    "input#billingState",
    "select#state",
    "input#state",
    'select[name="billingState"]',
    'input[name="billingState"]',
    'select[name="state"]',
    'input[name="state"]',
    'select[autocomplete="address-level1"]',
    'input[autocomplete="address-level1"]',
    'select[aria-label*="state" i]',
    'select[aria-label*="都道府県"]',
    'select[aria-label*="都道府県" i]',
    'select[name*="prefecture" i]',
    'select[id*="prefecture" i]',
    'select[name*="province" i]',
    'select[id*="province" i]',
    'input[placeholder*="state" i]',
    'input[aria-label*="state" i]',
    'input[placeholder*="都道府県"]',
    'input[aria-label*="都道府県"]',
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
PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS = (
    "#captcha-standalone",
    ".captcha-overlay",
    ".captcha-container",
)
PAYPAL_DISMISS_PROMPT_SELECTORS = [
    'button:has-text("OK")',
    'button:has-text("Ok")',
    'button:has-text("Okay")',
    'button:has-text("Not now")',
    'button:has-text("Maybe later")',
    'button:has-text("Skip")',
    'button:has-text("Close")',
    'button:has-text("Try another way")',
    'button:has-text("Use password instead")',
    'button:has-text("利用しない")',
    'button:has-text("閉じる")',
    'button:has-text("以后再说")',
    'button:has-text("暂不")',
    'button:has-text("改用密码")',
    '[role="dialog"] button:has-text("利用しない")',
    '[role="dialog"] button:has-text("Close")',
    '[role="dialog"] button[aria-label="Close"]',
    '[role="dialog"] button:has-text("OK")',
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
    "paypal_checkout_terms_ready": "checkout 条款已确认，准备提交",
    "paypal_submit_checkout": "正在提交 checkout 并跳转 PayPal",
    "paypal_wait_redirect": "已提交 checkout，等待跳转到 PayPal",
    "paypal_ssl_protocol_error_refresh": "PayPal SSL 连接错误，等待刷新重试",
    "paypal_ssl_protocol_error_retry_queued": "PayPal SSL 连接错误刷新后仍未恢复，加入待重试池",
    "paypal_authorize": "已进入 PayPal 页面，开始自动登录/授权",
    "paypal_login_email": "正在填写 PayPal 邮箱",
    "paypal_login_password": "正在填写 PayPal 密码",
    "paypal_create_account": "正在切换到 PayPal 注册流程",
    "paypal_signup_email": "正在填写 PayPal 注册邮箱",
    "paypal_wait_signup_form": "正在等待 PayPal 注册表单加载",
    "paypal_fill_signup": "正在填写 PayPal 注册表单",
    "paypal_submit_signup": "正在提交 PayPal 注册信息",
    "paypal_wait_signup_otp": "正在等待 PayPal 短信验证码",
    "paypal_otp_phone_lock_wait": "正在等待当前手机号验证码流程释放",
    "paypal_otp_phone_lock_acquired": "已锁定当前手机号验证码流程",
    "paypal_otp_phone_lock_released": "已释放当前手机号验证码流程",
    "paypal_otp_phone_lock_timeout": "等待当前手机号验证码流程释放超时",
    "paypal_wait_sms_otp_window": "等待短信平台下发 PayPal 验证码",
    "paypal_fetch_otp": "正在从接码接口拉取 PayPal 验证码",
    "paypal_sms_otp_resend_due": "长时间未收到 PayPal 验证码，尝试重新拉取/重发",
    "paypal_sms_provider_resend_triggered": "已通知接码平台继续接收 PayPal 验证码",
    "paypal_otp_resend_clicked": "60 秒未收到 PayPal 验证码，已点击 Resend",
    "paypal_otp_received": "已收到 PayPal 验证码",
    "paypal_submit_otp": "正在提交 PayPal 短信验证码",
    "paypal_phone_rejected_waiting_dismiss": "PayPal 拒绝当前手机号，正在关闭提示弹窗",
    "paypal_phone_rejected_rotate": "PayPal 拒绝当前手机号，切换下一个手机号重试",
    "paypal_phone_rejected_final": "PayPal 拒绝当前手机号，已标记为不可用",
    "paypal_replace_signup_phone": "PayPal 拒绝当前手机号，正在替换手机号字段",
    "paypal_card_rejected_retry": "PayPal 拒绝当前卡片，正在只替换卡片信息重试",
    "paypal_prompt_dismissed": "已关闭 PayPal 通行密钥/提示弹窗",
    "paypal_approve_clicked": "已点击 PayPal 同意并继续",
    "paypal_wait_result": "PayPal 已授权，等待商户页面确认结果",
    "paypal_wait_manual": "等待人工完成 PayPal 支付流程",
    "paypal_protocol_start": "协议模式：开始处理 PayPal checkout",
    "paypal_protocol_proxy_http_fallback": "SOCKS 代理握手失败，协议模式改用 HTTP 代理重试",
    "paypal_protocol_init": "协议模式：已初始化 Stripe checkout",
    "paypal_protocol_payment_method": "协议模式：已创建 PayPal payment_method",
    "paypal_protocol_confirm": "协议模式：已确认 Stripe checkout",
    "paypal_protocol_approve_url": "协议模式：已解析 PayPal 授权链接",
    "paypal_protocol_wait_result": "协议模式：等待 Stripe checkout 结果",
    "paypal_protocol_browser_fallback": "协议模式被 PayPal 风控拦截，正在降级到浏览器模式",
    "paypal_browser_fallback_navigate": "浏览器已打开 PayPal 授权页面",
    "paypal_browser_fallback_ddc_wait": "正在等待 DataDome 安全检查通过",
    "paypal_ddc_slider_detected": "检测到 DataDome 滑块验证，正在自动解题",
    "paypal_ddc_invisible_wait": "检测到 DataDome 隐形验证，等待自动通过",
    "paypal_ddc_blocked_retry": "检测到 DataDome 封锁页面，正在刷新重试",
    "paypal_ddc_blocked_final": "DataDome 封锁页面重试后仍未通过",
    "paypal_signup_email_reload": "邮箱提交后页面卡住，正在恢复重试",
    "paypal_agree_create_clicked": "已点击 PayPal 同意并创建账户",
    "paypal_return_wait": "等待订阅回跳确认",
    "paypal_return_confirmed": "订阅已回跳 ChatGPT/OpenAI 页面，绑定成功",
}


def classify_paypal_checkout_state(url: str, body_text: str):
    normalized_url = str(url or "").strip().lower()
    normalized_body = str(body_text or "").strip().lower()
    haystack = f"{normalized_url}\n{normalized_body}"
    parsed_url = urlsplit(normalized_url)
    query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    fragment_params = dict(parse_qsl(parsed_url.fragment, keep_blank_values=True))
    redirect_status = str(query_params.get("redirect_status") or fragment_params.get("redirect_status") or "").lower()
    stripe_return_success = (
        parsed_url.netloc.endswith("pm-redirects.stripe.com")
        and "/return" in parsed_url.path
        and (
            redirect_status in {"succeeded", "success", "complete", "completed"}
            or str(query_params.get("status") or fragment_params.get("status") or "").lower()
            in {"succeeded", "success", "complete", "completed"}
        )
    )
    chatgpt_success = parsed_url.netloc in {"chatgpt.com", "chat.openai.com"} and "/payments/success" in parsed_url.path

    if any(hint in haystack for hint in PAYPAL_ACCOUNT_LIMITED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_account_limited",
            "message": "PayPal 账号受限，无法完成授权",
        }

    if any(hint in haystack for hint in PAYPAL_PHONE_REJECTED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_phone_rejected",
            "message": "PayPal 拒绝当前手机号，请更换手机号",
        }

    if any(hint in haystack for hint in PAYPAL_CARD_LINKED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_card_linked",
            "message": "当前卡片已绑定到其他 PayPal 账号，需要换卡/换身份信息",
        }

    if any(hint in haystack for hint in PAYPAL_CARD_CANDIDATE_REJECTED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_card_candidate_rejected",
            "message": "PayPal 拒绝当前卡片/身份组合，需要换卡或账单身份信息",
        }

    if any(hint in haystack for hint in PAYPAL_DATADOME_BLOCKED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_datadome_blocked",
            "message": "PayPal DataDome/风控验证阻断当前环境",
        }

    if any(hint in haystack for hint in PAYPAL_HUMAN_VERIFICATION_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "paypal_human_verification",
            "message": "PayPal 人机验证等待人工处理",
        }

    if any(hint in haystack for hint in PAYPAL_FUNDING_REJECTED_HINTS):
        return {
            "status": "failed",
            "failure_stage": "paypal_funding_rejected",
            "message": "PayPal 拒绝当前资金来源，需要换卡/换身份信息",
        }

    if CANCEL_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in CANCEL_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付已取消",
        }

    if (
        stripe_return_success
        or chatgpt_success
        or redirect_status in {"succeeded", "success", "complete", "completed"}
        or "setup_intent=" in normalized_url and "redirect_pm_type=paypal" in normalized_url
        or SUCCESS_URL_RE.search(parsed_url.path)
        or any(hint in haystack for hint in SUCCESS_HINTS)
    ):
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到 PayPal/支付成功页面",
        }

    if FAILURE_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in FAILURE_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal/支付失败提示",
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


def _classify_paypal_stripe_payment_page(payload: dict[str, Any] | None):
    data = payload if isinstance(payload, dict) else {}
    setup_intent = data.get("setup_intent") if isinstance(data.get("setup_intent"), dict) else {}
    payment_intent = data.get("payment_intent") if isinstance(data.get("payment_intent"), dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    submission_attempt = data.get("submission_attempt") if isinstance(data.get("submission_attempt"), dict) else {}
    if not submission_attempt and isinstance(session.get("submission_attempt"), dict):
        submission_attempt = session.get("submission_attempt") or {}

    values = {
        "setup_intent": str(setup_intent.get("status") or "").strip().lower(),
        "payment_intent": str(payment_intent.get("status") or "").strip().lower(),
        "payment_status": str(data.get("payment_status") or "").strip().lower(),
        "status": str(data.get("status") or "").strip().lower(),
        "submission_attempt": str(submission_attempt.get("state") or "").strip().lower(),
    }
    summary = (
        f"submission_attempt={values['submission_attempt']!r} "
        f"setup_intent={values['setup_intent']!r} "
        f"payment_intent={values['payment_intent']!r} "
        f"payment_status={values['payment_status']!r} "
        f"status={values['status']!r}"
    )

    if (
        values["setup_intent"] in {"succeeded"}
        or values["payment_intent"] in {"succeeded"}
        or values["payment_status"] in {"paid", "no_payment_required", "succeeded"}
        or values["status"] in {"complete", "completed", "paid", "succeeded"}
        or values["submission_attempt"] in {"complete", "completed"}
    ):
        return {
            "status": "success",
            "failure_stage": "",
            "message": f"Stripe checkout 状态已确认成功: {summary}",
        }

    if (
        values["setup_intent"] in {"processing", "requires_action", "requires_confirmation"}
        or values["payment_intent"] in {"processing", "requires_action", "requires_confirmation"}
        or values["payment_status"] in {"processing", "pending"}
        or values["status"] in {"processing", "pending", "open"}
        or values["submission_attempt"] in {"processing", "requires_action", "requires_approval"}
    ):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": f"Stripe checkout 状态仍在处理中: {summary}",
        }

    if (
        values["setup_intent"] in {"canceled", "cancelled", "requires_payment_method"}
        or values["payment_intent"] in {"canceled", "cancelled", "requires_payment_method"}
        or values["payment_status"] in {"failed", "unpaid", "canceled", "cancelled"}
        or values["status"] in {"failed", "expired", "canceled", "cancelled"}
        or values["submission_attempt"] in {"failed", "canceled", "cancelled"}
    ):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": f"Stripe checkout 状态已确认失败: {summary}",
        }

    return None


def _fetch_paypal_stripe_payment_page_state(checkout_url: str, *, http: Any | None = None):
    checkout_session_id = _extract_checkout_session_id(checkout_url)
    if not checkout_session_id:
        return None

    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
        "elements_session_client[locale]": "en",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[stripe_js_locale]": "auto",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": DEFAULT_STRIPE_PK,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    client = http or _new_http_session(require_curl_cffi=False)
    try:
        resp = client.get(
            f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}",
            params=params,
            timeout=20,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except Exception:
        return None
    return _classify_paypal_stripe_payment_page(payload)


def _protocol_http_json(resp: Any, stage: str) -> dict:
    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} "
            f"{(getattr(resp, 'text', '') or '')[:300]}"
        ) from exc
    return payload if isinstance(payload, dict) else {"_raw": payload}


def _protocol_ensure_ok(resp: Any, stage: str) -> dict:
    status_code = int(getattr(resp, "status_code", 0) or 0)
    if 200 <= status_code < 300:
        return _protocol_http_json(resp, stage)
    text = str(getattr(resp, "text", "") or "")
    lowered = text.lower()
    if any(hint in text.lower() for hint in PAYPAL_DATADOME_BLOCKED_HINTS + PAYPAL_HUMAN_VERIFICATION_HINTS):
        raise RuntimeError(f"{stage} 被 PayPal/Stripe 风控拦截，需要切换浏览器模式或人工处理: HTTP {status_code}")
    if stage == "paypal_protocol_confirm" and "payment_method_types_mismatch" in lowered:
        raise RuntimeError(
            f"{stage} 失败: 当前 checkout session 未启用 PayPal 支付方式，"
            "请重新生成支持 PayPal 的 US/USD checkout 后再走协议无卡流程"
        )
    raise RuntimeError(f"{stage} 失败: HTTP {status_code} {text[:500]}")


def _paypal_protocol_elements_options() -> dict[str, str]:
    return {
        "elements_options_client[stripe_js_locale]": "auto",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
    }


def _paypal_protocol_checkout_amount(payload: dict) -> str:
    total_summary = payload.get("total_summary") if isinstance(payload.get("total_summary"), dict) else {}
    invoice = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else {}
    if total_summary.get("due") is not None:
        return str(total_summary["due"])
    if invoice.get("amount_due") is not None:
        return str(invoice["amount_due"])
    line_items = payload.get("line_items") if isinstance(payload.get("line_items"), list) else []
    if line_items:
        try:
            return str(sum(int(item.get("amount") or 0) for item in line_items if isinstance(item, dict)))
        except Exception:
            return "0"
    return "0"


def _paypal_protocol_amount_due(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        digits = re.sub(r"\D+", "", str(value or ""))
        return int(digits or "0")


def _paypal_protocol_payment_method_types(payload: Any) -> set[str]:
    found: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key or ""))
            return
        if isinstance(value, (list, tuple)):
            if key in {"payment_method_types", "ordered_payment_method_types", "automatic_payment_method_types"}:
                for item in value:
                    if isinstance(item, str):
                        found.add(item.strip().lower())
            for item in value:
                visit(item)

    visit(payload)
    return found


STRIPE_VERSION_BASE = "2025-03-31.basil"


def _paypal_protocol_stripe_init(http: Any, checkout_session_id: str, stripe_pk: str) -> dict:
    stripe_js_id = str(uuid.uuid4())
    elements_session_id = f"elements_session_{uuid.uuid4().hex[:11]}"
    elements_options = _paypal_protocol_elements_options()
    url = f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/init"

    # 先用基础版本（不带 beta/elements_options），失败再用完整版本降级
    for version, include_betas in [
        (STRIPE_VERSION_BASE, False),
        (STRIPE_VERSION_FULL, True),
    ]:
        data = {
            "browser_locale": "en-US",
            "browser_timezone": "Asia/Shanghai",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": stripe_js_id,
            "elements_session_client[locale]": "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "_stripe_version": version,
            "key": stripe_pk,
        }
        if include_betas:
            data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
            data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
            data.update(elements_options)

        resp = http.post(url, data=data, timeout=30)
        status_code = int(getattr(resp, "status_code", 0) or 0)
        if status_code == 200:
            payload = _protocol_http_json(resp, "paypal_protocol_stripe_init")
            init_checksum = str(payload.get("init_checksum") or "")
            if not init_checksum:
                raise RuntimeError(f"paypal_protocol_stripe_init 未返回 init_checksum: {payload}")
            return {
                "raw": payload,
                "init_checksum": init_checksum,
                "stripe_js_id": stripe_js_id,
                "elements_session_id": elements_session_id,
                "elements_session_config_id": str(uuid.uuid4()),
                "elements_options_client": elements_options if include_betas else {},
                "config_id": str(payload.get("config_id") or ""),
                "expected_amount": _paypal_protocol_checkout_amount(payload),
                "currency": str(payload.get("currency") or "usd").lower(),
                "return_url": str(payload.get("return_url") or ""),
                "stripe_hosted_url": str(payload.get("stripe_hosted_url") or ""),
                "locale": str(payload.get("locale") or "en"),
                "stripe_version": version,
            }
        if status_code == 400 and "beta" in str(getattr(resp, "text", "") or "").lower():
            logger.info("[paypal_protocol] init version=%s rejected (beta), trying next...", version[:30])
            continue
        if status_code == 400 and "parameter_unknown" in str(getattr(resp, "text", "") or "").lower():
            logger.info("[paypal_protocol] init version=%s rejected (unknown param), trying next...", version[:30])
            continue
        # 非 400 降级场景，直接报错
        _protocol_ensure_ok(resp, "paypal_protocol_stripe_init")

    raise RuntimeError("paypal_protocol_stripe_init 失败: 所有 Stripe API 版本均不可用")


def _paypal_protocol_elements_session(http: Any, checkout_session_id: str, stripe_pk: str, init_ctx: dict) -> None:
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    params = {
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": str(int(re.sub(r"\D+", "", str(init_ctx.get("expected_amount") or "0")) or "0")),
        "deferred_intent[currency]": str(init_ctx.get("currency") or "usd").lower(),
        "deferred_intent[setup_future_usage]": "off_session",
        "deferred_intent[payment_method_types][0]": "paypal",
        "currency": str(init_ctx.get("currency") or "usd").lower(),
        "key": stripe_pk,
        "_stripe_version": effective_version,
        "elements_init_source": "custom_checkout",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": init_ctx["stripe_js_id"],
        "locale": init_ctx.get("locale") or "en",
        "type": "deferred_intent",
        "checkout_session_id": checkout_session_id,
    }
    # 仅在完整版本时添加 client_betas
    if "checkout_server_update_beta" in effective_version:
        params["client_betas[0]"] = "custom_checkout_server_updates_1"
        params["client_betas[1]"] = "custom_checkout_manual_approval_1"
    try:
        resp = http.get(f"{STRIPE_API}/v1/elements/sessions", params=params, timeout=30)
        if resp.status_code != 200:
            logger.info("[paypal_protocol] elements/sessions skipped: HTTP %s", resp.status_code)
            return
        payload = _protocol_http_json(resp, "paypal_protocol_elements_session")
    except Exception as exc:
        logger.info("[paypal_protocol] elements/sessions soft-failed: %s", exc)
        return
    real_session_id = str(payload.get("session_id") or payload.get("id") or "")
    if real_session_id:
        init_ctx["elements_session_id"] = real_session_id
    if payload.get("config_id"):
        init_ctx["config_id"] = str(payload.get("config_id") or "")
    if payload.get("payment_method_checkout_config_id"):
        init_ctx["payment_method_checkout_config_id"] = str(payload.get("payment_method_checkout_config_id") or "")
    if payload.get("elements_session_config_id"):
        init_ctx["elements_session_config_id"] = str(payload.get("elements_session_config_id") or "")


def _paypal_protocol_update_payment_page_address(http: Any, checkout_session_id: str, stripe_pk: str, init_ctx: dict, billing: dict[str, str]) -> None:
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    base = {
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": init_ctx.get("elements_session_id") or f"elements_session_{uuid.uuid4().hex[:11]}",
        "elements_session_client[stripe_js_id]": init_ctx.get("stripe_js_id") or str(uuid.uuid4()),
        "elements_session_client[locale]": init_ctx.get("locale") or "en",
        "elements_session_client[is_aggregation_expected]": "false",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "key": stripe_pk,
        "_stripe_version": effective_version,
    }
    if "checkout_server_update_beta" in effective_version:
        base["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
        base["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
    base.update(init_ctx.get("elements_options_client") or {})
    data = dict(base)
    data.update(
        {
            "tax_region[country]": str(billing.get("country") or "US").strip() or "US",
            "tax_region[line1]": str(billing.get("address1") or "").strip(),
            "tax_region[city]": str(billing.get("city") or "").strip(),
            "tax_region[state]": str(billing.get("state") or "").strip(),
            "tax_region[postal_code]": str(billing.get("zip") or "").strip(),
        }
    )
    try:
        resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}", data=data, timeout=30)
        if resp.status_code >= 400:
            logger.info("[paypal_protocol] address update soft-failed: HTTP %s %s", resp.status_code, (resp.text or "")[:180])
    except Exception as exc:
        logger.info("[paypal_protocol] address update soft-failed: %s", exc)


def _paypal_protocol_create_payment_method(http: Any, checkout_session_id: str, stripe_pk: str, init_ctx: dict, billing: dict[str, str], email: str) -> str:
    runtime = _stripe_runtime_from_env()
    runtime_version = runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    data = {
        "type": "paypal",
        "billing_details[name]": billing.get("name") or DEFAULT_PAYPAL_NAME,
        "billing_details[email]": email or billing.get("email") or "buyer@example.com",
        "billing_details[address][country]": billing.get("country") or "US",
        "billing_details[address][line1]": billing.get("address1") or "",
        "billing_details[address][city]": billing.get("city") or "",
        "billing_details[address][postal_code]": billing.get("zip") or "",
        "billing_details[address][state]": billing.get("state") or "",
        "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
        "referrer": "https://chatgpt.com",
        "time_on_page": str(25000 + secrets.randbelow(30001)),
        "client_attribution_metadata[client_session_id]": init_ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[checkout_config_id]": init_ctx.get("payment_method_checkout_config_id") or init_ctx.get("config_id") or "",
        "client_attribution_metadata[elements_session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": init_ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "guid": init_ctx.get("guid") or uuid.uuid4().hex,
        "muid": init_ctx.get("muid") or uuid.uuid4().hex,
        "sid": init_ctx.get("sid") or uuid.uuid4().hex,
        "_stripe_version": effective_version,
        "key": stripe_pk,
    }
    resp = http.post(f"{STRIPE_API}/v1/payment_methods", data=data, timeout=30)
    payload = _protocol_ensure_ok(resp, "paypal_protocol_payment_method")
    payment_method_id = str(payload.get("id") or "")
    if not payment_method_id.startswith("pm_"):
        raise RuntimeError(f"paypal_protocol_payment_method 返回异常: {payload}")
    return payment_method_id


def _paypal_protocol_confirm_checkout(http: Any, checkout_url: str, checkout_session_id: str, stripe_pk: str, init_ctx: dict, payment_method_id: str) -> dict:
    chatgpt_return = (
        f"https://chatgpt.com/checkout/verify?stripe_session_id={checkout_session_id}"
        "&processor_entity=openai_llc&plan_type=plus"
    )
    return_url = (
        f"https://checkout.stripe.com/c/pay/{checkout_session_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url={quote(chatgpt_return, safe='')}"
    )
    if init_ctx.get("stripe_hosted_url") and init_ctx.get("return_url"):
        return_url = (
            f"{init_ctx['stripe_hosted_url']}?returned_from_redirect=true"
            f"&ui_mode=custom&return_url={quote(str(init_ctx['return_url']), safe='')}"
        )
    elif init_ctx.get("return_url"):
        return_url = str(init_ctx["return_url"])
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    runtime = _stripe_runtime_from_env()
    data = {
        "guid": init_ctx.get("guid") or uuid.uuid4().hex,
        "muid": init_ctx.get("muid") or uuid.uuid4().hex,
        "sid": init_ctx.get("sid") or uuid.uuid4().hex,
        "payment_method": payment_method_id,
        "init_checksum": init_ctx["init_checksum"],
        "version": runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION,
        "expected_amount": init_ctx.get("expected_amount") or "0",
        "expected_payment_method_type": "paypal",
        "return_url": return_url,
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": init_ctx["stripe_js_id"],
        "elements_session_client[locale]": init_ctx.get("locale") or "en",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_session_client[session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[client_session_id]": init_ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": checkout_session_id,
        "client_attribution_metadata[checkout_config_id]": init_ctx.get("config_id", ""),
        "client_attribution_metadata[elements_session_id]": init_ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": init_ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "consent[terms_of_service]": "accepted",
        "_stripe_version": effective_version,
        "key": stripe_pk,
    }
    if "checkout_server_update_beta" in effective_version:
        data["elements_session_client[client_betas][0]"] = "custom_checkout_server_updates_1"
        data["elements_session_client[client_betas][1]"] = "custom_checkout_manual_approval_1"
    data.update(init_ctx.get("elements_options_client") or {})
    if runtime.get("js_checksum"):
        data["js_checksum"] = runtime["js_checksum"]
    if runtime.get("rv_timestamp"):
        data["rv_timestamp"] = runtime["rv_timestamp"]
    resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/confirm", data=data, timeout=30)
    return _protocol_ensure_ok(resp, "paypal_protocol_confirm")


def _paypal_protocol_unescape_url(value: str) -> str:
    return (
        str(value or "")
        .replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("&#x26;", "&")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )


def _paypal_protocol_extract_url_from_text(value: str) -> str:
    text = _paypal_protocol_unescape_url(value).strip()
    if not text:
        return ""
    if text.startswith("http") and (
        "paypal.com" in text.lower() or "pm-redirects.stripe.com" in text.lower()
    ):
        return text.strip("\"'<> ")
    for match in re.finditer(r"https?://[^\s\"'<>\\]+", text, re.I):
        url = match.group(0).rstrip("),.;")
        lowered = url.lower()
        if "paypal.com" in lowered or "pm-redirects.stripe.com" in lowered:
            return url
    return ""


def _paypal_protocol_extract_ba_token(url: str, fallback: str = "") -> str:
    try:
        params = dict(parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True))
    except Exception:
        params = {}
    for name in ("ba_token", "baToken", "billingAgreementId", "billing_agreement_id", "token"):
        value = str(params.get(name) or "").strip()
        if value.upper().startswith("BA-"):
            return value
    match = re.search(r"\bBA-[A-Z0-9-]{6,}\b", str(url or ""), re.I)
    if match:
        return match.group(0)
    return fallback


def _find_paypal_redirect_url(payload: Any) -> str:
    seen: set[int] = set()

    def walk(value: Any) -> str:
        marker = id(value)
        if marker in seen:
            return ""
        seen.add(marker)
        if isinstance(value, str):
            found = _paypal_protocol_extract_url_from_text(value)
            if found:
                return found
            return ""
        if isinstance(value, dict):
            if value.get("type") == "redirect_to_url" and isinstance(value.get("redirect_to_url"), dict):
                url = _paypal_protocol_extract_url_from_text(str((value.get("redirect_to_url") or {}).get("url") or ""))
                if url:
                    return url
            for key in ("url", "href", "return_url", "redirect_url"):
                url = _paypal_protocol_extract_url_from_text(str(value.get(key) or ""))
                if url:
                    return url
            for nested in value.values():
                found = walk(nested)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = walk(item)
                if found:
                    return found
        return ""

    return walk(payload)


def _paypal_protocol_resolve_approve_url(http: Any, redirect_url: str) -> tuple[str, str]:
    current = str(redirect_url or "").strip()
    ba_token = ""
    for _ in range(8):
        if not current:
            break
        current = _paypal_protocol_unescape_url(current)
        parsed = urlsplit(current)
        ba_token = _paypal_protocol_extract_ba_token(current, ba_token)
        if _safe_host(current).endswith("paypal.com") and (
            "/agreements/approve" in parsed.path
            or "/checkoutweb/signup" in parsed.path
            or (parsed.path == "/pay" and ba_token)
        ):
            return current, ba_token
        try:
            resp = http.get(current, allow_redirects=False, timeout=30)
        except Exception as exc:
            raise RuntimeError(f"解析 PayPal redirect 失败: {exc}") from exc
        text = str(getattr(resp, "text", "") or "")
        if any(hint in text.lower() for hint in PAYPAL_DATADOME_BLOCKED_HINTS + PAYPAL_HUMAN_VERIFICATION_HINTS):
            raise RuntimeError("PayPal redirect 返回风控/人机验证页面，协议模式停止")
        location = resp.headers.get("location") or resp.headers.get("Location") or ""
        if location:
            location = _paypal_protocol_unescape_url(location)
            if location.startswith("/"):
                current = f"{parsed.scheme}://{parsed.netloc}{location}"
            else:
                current = location
            continue
        found_url = _paypal_protocol_extract_url_from_text(text)
        if found_url:
            current = found_url
            continue
        if 200 <= int(getattr(resp, "status_code", 0) or 0) < 300 and _safe_host(current).endswith("paypal.com"):
            return current, ba_token
        break
    return current, ba_token


def _paypal_protocol_wait_checkout_result(
    http: Any,
    *,
    checkout_url: str,
    return_url: str = "",
    timeout_seconds: int,
    on_progress=None,
):
    if return_url:
        try:
            http.get(return_url, timeout=30, allow_redirects=True)
        except Exception as exc:
            logger.info("[paypal_protocol] return_url follow soft-failed: %s", exc)
    deadline = time.time() + max(30, min(int(timeout_seconds or 90), 180))
    last_processing_message = ""
    while time.time() < deadline:
        state = _fetch_paypal_stripe_payment_page_state(checkout_url, http=http)
        if state and state.get("status") in {"success", "failed"}:
            return state
        if state and state.get("status") == "needs_review":
            last_processing_message = str(state.get("message") or "")
        _emit_progress(on_progress, _progress_event("paypal_protocol_wait_result", checkout_url=checkout_url))
        time.sleep(PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS)
    return _build_result(
        "needs_review",
        failure_stage="post_submit",
        message=last_processing_message or "协议模式已完成 PayPal authorize，但未在时限内确认最终支付状态",
    )


def _paypal_protocol_socks_invalid_response(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return (
        "curl: (97)" in text
        or "invalid version in initial socks5 response" in text
        or "received invalid version in initial socks5 response" in text
    )


def _paypal_protocol_http_proxy_fallback_url(proxy_url: str | None) -> str:
    try:
        normalized = normalize_proxy_url(proxy_url)
    except Exception:
        return ""
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"socks5", "socks5h"}:
        return ""
    if not (parsed.username or parsed.password):
        return ""
    return urlunsplit(("http", parsed.netloc, "", "", ""))


def _paypal_protocol_transient_transport_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        hint in lowered
        for hint in (
            "curl: (28)",
            "recv failure",
            "connection was reset",
            "operation timed out",
            "connection timed out",
            "remote disconnected",
            "connection aborted",
        )
    )


def _run_paypal_protocol_flow(
    *,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    paypal_mode: str,
    signup_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None,
    billing_payload: dict[str, str],
    timeout_seconds: int,
    paypal_country: str = "US",
    paypal_lang: str = "en",
    is_cancelled=None,
    on_progress=None,
):
    if callable(is_cancelled) and is_cancelled():
        return _build_result("failed", failure_stage="paypal_protocol", message="任务已取消")
    checkout_session_id = _extract_checkout_session_id(checkout_url)
    if not checkout_session_id:
        return _build_result("failed", failure_stage="paypal_protocol", message="协议模式无法识别 checkout session id")
    if not _has_complete_billing_payload(billing_payload):
        return _build_result("failed", failure_stage="paypal_protocol", message="协议模式账单地址缺少必要字段")
    paypal_country = _normalize_paypal_country(paypal_country or str(billing_payload.get("country") or "US"))
    paypal_lang = _normalize_paypal_lang(paypal_lang, paypal_country)

    protocol_proxy_url = proxy_url
    http = _new_http_session(protocol_proxy_url, require_curl_cffi=False)
    _emit_progress(on_progress, _progress_event("paypal_protocol_start", checkout_session_id=checkout_session_id))
    # 中间状态追踪，供浏览器降级使用
    _approve_url = ""
    _ba_token = ""
    _payment_method_id = ""
    try:
        try:
            init_ctx = _paypal_protocol_stripe_init(http, checkout_session_id, DEFAULT_STRIPE_PK)
        except Exception as exc:
            fallback_proxy_url = _paypal_protocol_http_proxy_fallback_url(protocol_proxy_url)
            if not fallback_proxy_url or not _paypal_protocol_socks_invalid_response(exc):
                raise
            logger.warning(
                "[paypal_protocol] SOCKS proxy handshake failed, retrying protocol flow with HTTP proxy: %s",
                _safe_proxy_summary(fallback_proxy_url),
            )
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_protocol_proxy_http_fallback",
                    proxy_url=_safe_proxy_summary(fallback_proxy_url),
                ),
            )
            protocol_proxy_url = fallback_proxy_url
            http = _new_http_session(protocol_proxy_url, require_curl_cffi=False)
            init_ctx = _paypal_protocol_stripe_init(http, checkout_session_id, DEFAULT_STRIPE_PK)
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_protocol_init",
                checkout_session_id=checkout_session_id,
                expected_amount=init_ctx.get("expected_amount"),
            ),
        )
        payment_method_types = _paypal_protocol_payment_method_types(init_ctx.get("raw"))
        if payment_method_types and "paypal" not in payment_method_types:
            return _build_result(
                "failed",
                failure_stage="paypal_payment_method_unavailable",
                message=(
                    "当前 checkout session 未启用 PayPal 支付方式 "
                    f"(payment_method_types={','.join(sorted(payment_method_types))})，"
                    "请重新生成支持 PayPal 的 US/USD checkout 后再走协议无卡流程"
                ),
            )
        if _paypal_protocol_amount_due(init_ctx.get("expected_amount")) != 0:
            return _build_result(
                "failed",
                failure_stage="browser_charge_guard",
                message=f"协议模式检测到 checkout 今日应付金额非 0 ({init_ctx.get('expected_amount')})，已跳过当前账号",
            )
        _paypal_protocol_elements_session(http, checkout_session_id, DEFAULT_STRIPE_PK, init_ctx)
        _paypal_protocol_update_payment_page_address(http, checkout_session_id, DEFAULT_STRIPE_PK, init_ctx, billing_payload)
        payment_method_id = _paypal_protocol_create_payment_method(
            http,
            checkout_session_id,
            DEFAULT_STRIPE_PK,
            init_ctx,
            billing_payload,
            email,
        )
        _emit_progress(on_progress, _progress_event("paypal_protocol_payment_method", payment_method_id=payment_method_id))
        _payment_method_id = payment_method_id
        confirm_payload = _paypal_protocol_confirm_checkout(
            http,
            checkout_url,
            checkout_session_id,
            DEFAULT_STRIPE_PK,
            init_ctx,
            payment_method_id,
        )
        _emit_progress(on_progress, _progress_event("paypal_protocol_confirm", checkout_session_id=checkout_session_id))
        stripe_classified = _classify_paypal_stripe_payment_page(confirm_payload)
        if stripe_classified and stripe_classified.get("status") in {"success", "failed"}:
            return stripe_classified
        redirect_url = _find_paypal_redirect_url(confirm_payload)
        if not redirect_url:
            return _build_result(
                "needs_review",
                failure_stage="paypal_protocol_redirect",
                message="协议模式已确认 Stripe checkout，但未在响应中找到 PayPal 授权链接",
            )
        approve_url, ba_token = _paypal_protocol_resolve_approve_url(http, redirect_url)
        _approve_url = approve_url
        _ba_token = ba_token
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_protocol_approve_url",
                paypal_approve_url=_safe_url_summary(approve_url),
                ba_token=ba_token,
            ),
        )
        if paypal_mode != "create_account":
            result = _build_result(
                "needs_review",
                failure_stage="paypal_protocol_authorize",
                message="协议模式已生成 PayPal 授权链接；已有账号登录授权暂未接管，请切回浏览器模式或人工完成授权",
            )
            result["paypal_approve_url"] = approve_url
            result["ba_token"] = ba_token
            result["payment_method_id"] = payment_method_id
            return result

        signup_profiles = _paypal_signup_profiles_for_phone_pool(signup_profile, phone_accounts)
        if not signup_profiles:
            signup_profiles = [dict(signup_profile or {})]
        if not signup_profiles or not any(str(item.get("phone") or "").strip() and str(item.get("sms_url") or "").strip() for item in signup_profiles):
            return _build_result(
                "failed",
                failure_stage="paypal_protocol",
                message="协议模式自动注册需要可用手机号和接码 API",
            )
        last_result = _build_result("failed", failure_stage="paypal_protocol", message="协议模式缺少可用注册资料")
        for signup_index, current_profile in enumerate(signup_profiles, start=1):
            if callable(is_cancelled) and is_cancelled():
                return _build_result("failed", failure_stage="paypal_protocol", message="任务已取消")
            phone = str(current_profile.get("phone") or "")
            sms_url = str(current_profile.get("sms_url") or "")
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_create_account",
                    f"协议模式：开始处理第 {signup_index}/{len(signup_profiles)} 个手机号",
                    phone=phone,
                    sms_url=_safe_url_summary(sms_url),
                    phone_pool_index=signup_index,
                    phone_pool_total=len(signup_profiles),
                ),
            )
            protocol_signup_result = run_paypal_no_card_protocol_signup(
                http,
                ba_token=ba_token,
                signup_profile=current_profile,
                timeout_seconds=max(90, timeout_seconds),
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                locale_country=str(current_profile.get("country") or billing_payload.get("country") or paypal_country).strip().upper() or paypal_country,
                locale_lang=paypal_lang,
            )
            protocol_signup_result["paypal_approve_url"] = approve_url
            protocol_signup_result["ba_token"] = protocol_signup_result.get("ba_token") or ba_token
            protocol_signup_result["payment_method_id"] = payment_method_id
            last_result = protocol_signup_result
            if (
                protocol_signup_result.get("failure_stage") == "paypal_phone_rejected"
                and signup_index < len(signup_profiles)
            ):
                _emit_progress(
                    on_progress,
                    _progress_event(
                        "paypal_phone_rejected_rotate",
                        rejected_phone=protocol_signup_result.get("rejected_phone") or phone,
                        next_phone=str(signup_profiles[signup_index].get("phone") or ""),
                        phone_pool_index=signup_index + 1,
                        phone_pool_total=len(signup_profiles),
                        level="warn",
                    ),
                )
                continue
            if protocol_signup_result.get("failure_stage") == "paypal_phone_rejected":
                _emit_progress(
                    on_progress,
                    _progress_event(
                        "paypal_phone_rejected_final",
                        rejected_phone=protocol_signup_result.get("rejected_phone") or phone,
                        phone_pool_index=signup_index,
                        phone_pool_total=len(signup_profiles),
                        level="warn",
                    ),
                )
            if protocol_signup_result.get("status") == "success":
                wait_result = _paypal_protocol_wait_checkout_result(
                    http,
                    checkout_url=checkout_url,
                    return_url=str(protocol_signup_result.get("return_url") or ""),
                    timeout_seconds=max(60, min(timeout_seconds, 180)),
                    on_progress=on_progress,
                )
                wait_result["paypal_approve_url"] = approve_url
                wait_result["ba_token"] = protocol_signup_result.get("ba_token") or ba_token
                wait_result["payment_method_id"] = payment_method_id
                wait_result["return_url"] = protocol_signup_result.get("return_url") or ""
                wait_result["paypal_user_id"] = protocol_signup_result.get("paypal_user_id") or ""
                return wait_result
            protocol_signup_result.setdefault("paypal_approve_url", approve_url)
            protocol_signup_result.setdefault("ba_token", ba_token)
            protocol_signup_result.setdefault("payment_method_id", payment_method_id)
            return protocol_signup_result
        last_result.setdefault("paypal_approve_url", approve_url)
        last_result.setdefault("ba_token", ba_token)
        last_result.setdefault("payment_method_id", payment_method_id)
        return last_result
    except Exception as exc:
        logger.exception("[paypal_protocol] failed")
        raw_message = str(exc)
        failure_stage = "paypal_protocol"
        if "paypal_human_verification" in raw_message:
            failure_stage = "paypal_human_verification"
        result = _build_result(
            "failed" if failure_stage != "paypal_human_verification" else "needs_review",
            failure_stage=failure_stage,
            message=f"协议模式失败: {exc}",
        )
        # 附带中间状态供浏览器降级使用
        if _approve_url:
            result["paypal_approve_url"] = _approve_url
        if _ba_token:
            result["ba_token"] = _ba_token
        if _payment_method_id:
            result["payment_method_id"] = _payment_method_id
        return result


def _paypal_protocol_needs_browser_fallback(result: dict) -> bool:
    """判断协议模式结果是否需要降级到浏览器。仅对风控/人机验证类失败降级。"""
    if result.get("status") == "success":
        return False
    stage = str(result.get("failure_stage") or "")
    has_fallback_target = bool(result.get("paypal_approve_url") or result.get("ba_token"))
    if stage in {"paypal_human_verification", "paypal_protocol_authorize"}:
        # 有 approve_url 才能降级
        return has_fallback_target
    if stage == "paypal_protocol" and has_fallback_target:
        return _paypal_protocol_transient_transport_error(str(result.get("message") or ""))
    return False


def _safe_host(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _is_paypal_host(url: str) -> bool:
    return _safe_host(url).endswith("paypal.com")


def _is_paypal_ssl_protocol_error_page(url: str, body_text: str = "") -> bool:
    text = f"{url}\n{body_text}".lower()
    if not _is_paypal_host(url) and "paypal.com" not in text:
        return False
    return (
        "err_ssl_protocol_error" in text
        or "sent an invalid response" in text
        or "can't provide a secure connection" in text
        or "cannot provide a secure connection" in text
        or ("this site" in text and "secure connection" in text and "paypal.com" in text)
    )


def _is_checkout_host(url: str) -> bool:
    host = _safe_host(url)
    if host in {"pay.openai.com", "checkout.stripe.com"}:
        return True
    return host == "chatgpt.com" and "/checkout/" in str(url or "").lower()


def _is_chatgpt_or_openai_return_url(url: str) -> bool:
    host = _safe_host(url)
    return host == "chatgpt.com" or host == "openai.com" or host.endswith(".openai.com")


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


def _luhn_check_digit(prefix: str) -> str:
    digits = [int(ch) for ch in re.sub(r"\D+", "", str(prefix or ""))]
    total = 0
    parity = (len(digits) + 1) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - (total % 10)) % 10)


def _is_luhn_valid(value: str) -> bool:
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


def _paypal_card_brand_allowed(value: str) -> bool:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 15 and digits[:2] in {"34", "37"}:
        return True
    if len(digits) == 16 and digits.startswith("4"):
        return True
    if len(digits) == 16 and 51 <= int(digits[:2] or "0") <= 55:
        return True
    if len(digits) == 16 and 2221 <= int(digits[:4] or "0") <= 2720:
        return True
    return False


def _generate_paypal_card_number() -> str:
    prefixes = ("4539", "4485", "4716", "5200", "5424", "2221", "3782")
    prefix = secrets.choice(prefixes)
    length = 15 if prefix.startswith(("34", "37")) else 16
    body_len = length - len(prefix) - 1
    body = prefix + "".join(secrets.choice(string.digits) for _ in range(body_len))
    return body + _luhn_check_digit(body)


def _normalize_or_generate_paypal_card_number(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if _paypal_card_brand_allowed(digits) and _is_luhn_valid(digits):
        return digits
    return _generate_paypal_card_number()


def _generate_paypal_card_expiry() -> str:
    month = secrets.randbelow(12) + 1
    year = 2029 + secrets.randbelow(4)
    return f"{month:02d} / {str(year)[-2:]}"


def _generate_paypal_card_cvv(card_number: str = "") -> str:
    length = 4 if re.sub(r"\D+", "", str(card_number or "")).startswith(("34", "37")) else 3
    first = secrets.choice("123456789")
    return first + "".join(secrets.choice(string.digits) for _ in range(length - 1))


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
        result["card_number"] = _normalize_or_generate_paypal_card_number(card_number)
    else:
        result["card_number"] = _generate_paypal_card_number()
    if card_expiry:
        result["card_expiry"] = card_expiry
    else:
        result["card_expiry"] = _generate_paypal_card_expiry()
    if card_cvv:
        result["card_cvv"] = card_cvv
    else:
        result["card_cvv"] = _generate_paypal_card_cvv(result.get("card_number") or "")
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
    phone_accounts: list[dict] | None = None,
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
) -> dict[str, str | bool]:
    billing = dict(billing_payload or {})
    first_name, last_name = _split_paypal_name(str(billing.get("name") or ""))
    email = str(paypal_email or "").strip() or _generate_random_paypal_email()
    password = str(paypal_password or "").strip() or _generate_random_paypal_password()
    card_number = _normalize_or_generate_paypal_card_number(
        str(paypal_card_number or "").strip() or _first_payload_value(billing, "card_number", "cardNumber")
    )
    card_expiry = str(paypal_card_expiry or "").strip() or _first_payload_value(
        billing,
        "card_expiry",
        "cardExpiry",
        "expiry",
        "expiry_date",
    ) or _generate_paypal_card_expiry()
    card_cvv = str(paypal_card_cvv or "").strip() or _first_payload_value(billing, "card_cvv", "cardCvv", "cvv", "cvc")
    if not re.sub(r"\D+", "", card_cvv):
        card_cvv = _generate_paypal_card_cvv(card_number)
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
        "card_number": card_number,
        "card_expiry": _normalize_paypal_card_expiry(card_expiry),
        "card_cvv": re.sub(r"\D+", "", card_cvv),
    }


def _normalize_paypal_phone_account(raw: Any, *, fallback_otp_channel: str = "sms") -> dict[str, str]:
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
    otp_channel = str(raw.get("otp_channel") or raw.get("otpChannel") or fallback_otp_channel or "sms").strip().lower() or "sms"
    if not phone or not sms_url:
        return {}
    if otp_channel not in {"sms", "whatsapp"}:
        otp_channel = "sms"
    return {"phone": phone, "sms_url": sms_url, "otp_channel": otp_channel}


def _paypal_signup_profiles_for_phone_pool(
    base_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None,
) -> list[dict[str, str | bool]]:
    if not base_profile:
        return []
    fallback_otp_channel = str(base_profile.get("otp_channel") or "sms")
    normalized_accounts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in phone_accounts or []:
        account = _normalize_paypal_phone_account(raw, fallback_otp_channel=fallback_otp_channel)
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
        profile["phone"] = _normalize_paypal_phone(account["phone"])
        profile["sms_url"] = account["sms_url"]
        profile["otp_channel"] = account["otp_channel"]
        profile["phone_pool_index"] = str(index)
        profile["phone_pool_total"] = str(total)
        profiles.append(profile)
    return profiles or [dict(base_profile)]


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
    requested_country = _normalize_paypal_country(requested.get("country") or "US")
    if requested_country in DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES:
        generated_raw = dict(DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES[requested_country])
    else:
        requested_country = "US"
        generated_raw = _fetch_paypal_random_billing_profile()
    generated = _public_paypal_billing_info(generated_raw)
    merged = {
        "name": str(generated.get("name") or DEFAULT_PAYPAL_NAME).strip() or DEFAULT_PAYPAL_NAME,
        "email": str(requested.get("email") or "").strip(),
        "phone": str(requested.get("phone") or generated.get("phone_number") or "").strip(),
        "country": requested_country,
        "state": str(generated.get("state") or "").strip(),
        "city": str(generated.get("city") or "").strip(),
        "zip": str(generated.get("zip") or "").strip(),
        "address1": str(generated.get("address1") or "").strip(),
        "address2": str(generated.get("address2") or "").strip(),
    }
    card_fields = {
        "card_number": _first_payload_value(generated_raw, "card_number", "cardNumber"),
        "card_expiry": _first_payload_value(
            generated_raw,
            "card_expiry",
            "cardExpiry",
            "expiry",
            "expiry_date",
        ),
        "card_cvv": _first_payload_value(generated_raw, "card_cvv", "cardCvv", "cvv", "cvc"),
    }
    for key, value in card_fields.items():
        if value:
            merged[key] = str(value).strip()
    merged["card_number"] = _normalize_or_generate_paypal_card_number(merged.get("card_number") or "")
    merged["card_expiry"] = str(merged.get("card_expiry") or "").strip() or _generate_paypal_card_expiry()
    merged["card_cvv"] = re.sub(r"\D+", "", str(merged.get("card_cvv") or "")) or _generate_paypal_card_cvv(merged["card_number"])
    return merged


def _resolve_checkout_billing_payload(payload: dict | None, *, auto_generate: bool) -> dict[str, str]:
    if auto_generate:
        return _merge_checkout_billing_payload(payload)
    requested = _build_checkout_billing_payload(payload)
    if not str(requested.get("name") or "").strip():
        requested["name"] = DEFAULT_PAYPAL_NAME
    if not str(requested.get("country") or "").strip():
        requested["country"] = "US"
    return requested


def _has_complete_billing_payload(payload: dict[str, str]) -> bool:
    required = ("name", "country", "state", "city", "zip", "address1")
    return all(str(payload.get(key) or "").strip() for key in required)


def _paypal_hosted_captcha_bypass_function_source() -> str:
    selectors_json = ", ".join(json.dumps(selector) for selector in PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS)
    return f"""() => {{
      const sentinel = '__AUTOTEAM_PAYPAL_HOSTED_CAPTCHA_BYPASS__';
      const styleId = 'autoteam-paypal-hosted-captcha-bypass-style';
      const selectors = [{selectors_json}];
      const hideCss = selectors.map((selector) => `${{selector}} {{ display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }}`).join('\\n');
      const removeArtifacts = () => {{
        let removed = 0;
        selectors.forEach((selector) => {{
          document.querySelectorAll(selector).forEach((node) => {{
            try {{
              node.remove();
              removed += 1;
            }} catch (error) {{
              // Ignore non-removable overlays.
            }}
          }});
        }});
        return removed;
      }};
      if (!document.getElementById(styleId)) {{
        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = hideCss;
        (document.head || document.documentElement || document.body)?.appendChild(style);
      }}
      if (!window[sentinel]) {{
        const scheduleCleanup = () => {{
          try {{
            removeArtifacts();
          }} catch (error) {{
            // Ignore cleanup races during navigation.
          }}
        }};
        const root = document.documentElement || document.body;
        if (root && typeof MutationObserver !== 'undefined') {{
          const observer = new MutationObserver(scheduleCleanup);
          observer.observe(root, {{
            childList: true,
            subtree: true,
          }});
        }}
        if (typeof window.setInterval === 'function') {{
          window.setInterval(scheduleCleanup, 1000);
        }}
        window[sentinel] = true;
      }}
      return {{ installed: Boolean(window[sentinel]), removed: removeArtifacts() }};
    }}"""


def _ensure_paypal_hosted_captcha_bypass(api: ChatGPTTeamAPI) -> bool:
    context = getattr(api, "context", None)
    page = getattr(api, "page", None)
    if not context or not page:
        return False

    script = _paypal_hosted_captcha_bypass_function_source()
    if not getattr(api, "_paypal_hosted_captcha_bypass_installed", False):
        try:
            context.add_init_script(script=f"({script})();")
            setattr(api, "_paypal_hosted_captcha_bypass_installed", True)
        except Exception as exc:
            logger.info("[paypal_bind_executor] install PayPal captcha bypass init script failed: %s", exc)

    try:
        result = page.evaluate(script)
        if isinstance(result, dict) and int(result.get("removed") or 0) > 0:
            logger.info(
                "[paypal_bind_executor] removed PayPal hosted captcha artifacts: %s",
                result.get("removed"),
            )
        return True
    except Exception as exc:
        logger.info("[paypal_bind_executor] execute PayPal captcha bypass failed: %s", exc)
        return False


# ──────── DataDome DDC 滑块检测与自动拖拽 ────────

_DDC_SLIDER_KEYWORDS = (
    "将滑块", "确认您是人类", "Slide the puzzle",
    "move the slider", "Move the slider", "滑动到最右",
    "Slide to continue", "slide to verify",
)

_DDC_BLOCKED_KEYWORDS = (
    "You have been blocked",
    "you have been blocked",
    "Access denied",
    "access denied",
    "Your request has been blocked",
    "请求已被拦截",
    "您的访问已被阻止",
)


def _is_ddc_blocked_page(page) -> bool:
    """检测 DataDome 'You have been blocked' 拦截页面。"""
    try:
        text = page.inner_text("body")[:3000]
    except Exception:
        return False
    return any(kw in text for kw in _DDC_BLOCKED_KEYWORDS)


def _is_ddc_frame_url(url: str) -> bool:
    """DataDome frame URL 判断。避免把普通 captcha/hCaptcha iframe 误判成 DDC。"""
    lowered = str(url or "").lower()
    return any(
        hint in lowered
        for hint in (
            "datadome",
            "captcha-delivery.com",
            "geo.captcha-delivery.com",
            "ddc.paypal.com",
            "geo.ddc.paypal.com",
        )
    )


def _ddc_slider_visible(page) -> bool:
    """检测主文档 + DataDome iframe 中是否有滑块可见。"""
    try:
        pt = page.inner_text("body")[:2000]
        if any(kw in pt for kw in _DDC_SLIDER_KEYWORDS):
            return True
    except Exception:
        pass
    for fr in getattr(page, "frames", []) or []:
        u = fr.url or ""
        if u == page.url:
            continue
        if not _is_ddc_frame_url(u):
            continue
        try:
            txt = (fr.inner_text("body") or "")[:2000]
        except Exception:
            continue
        if any(kw in txt for kw in _DDC_SLIDER_KEYWORDS):
            return True
    return False


def _find_ddc_iframe(page):
    """查找 DataDome 相关 iframe frame 对象。"""
    for fr in getattr(page, "frames", []) or []:
        if _is_ddc_frame_url(fr.url or ""):
            return fr
    return None


def _has_ddc_iframe(page) -> bool:
    """检测是否存在 DataDome iframe（可能是隐形挑战）。"""
    return _find_ddc_iframe(page) is not None


def _try_solve_ddc_slider(page, *, attempts: int = 2) -> bool:
    """尝试通过拖拽方式解决 DataDome 可见滑块。成功返回 True。"""
    import random as _random

    for attempt in range(attempts):
        fr = _find_ddc_iframe(page)
        if not fr:
            return False
        # 定位 iframe 元素在主文档中的位置
        iframe_el = None
        for sel in ['iframe[src*="datadome"]', 'iframe[src*="captcha-delivery.com"]', 'iframe[src*="ddc.paypal.com"]']:
            iframe_el = page.query_selector(sel)
            if iframe_el:
                break
        if not iframe_el:
            return False
        try:
            iframe_box = iframe_el.bounding_box()
        except Exception:
            iframe_box = None
        if not iframe_box:
            return False
        # 查找滑块 handle
        handle = None
        for sel in [
            '.slider', '[role="slider"]',
            '.slider-handle', '.sliderIcon',
            'div[class*="slider"]', 'button[class*="slider"]',
            '#ddv1-captcha-container .slider',
        ]:
            try:
                el = fr.query_selector(sel)
            except Exception:
                el = None
            if el:
                try:
                    if el.is_visible():
                        handle = el
                        break
                except Exception:
                    pass
        if not handle:
            return False
        try:
            hb = handle.bounding_box()
        except Exception:
            hb = None
        if not hb:
            return False
        # 绝对坐标
        start_x = iframe_box["x"] + hb["x"] + hb["width"] / 2
        start_y = iframe_box["y"] + hb["y"] + hb["height"] / 2
        end_x = iframe_box["x"] + iframe_box["width"] - 10
        end_y = start_y
        logger.info(
            "[paypal_ddc] drag attempt=%d start=(%.0f,%.0f) end=(%.0f,%.0f)",
            attempt + 1, start_x, start_y, end_x, end_y,
        )
        # 人类化拖动 — 使用 Playwright 原生 steps 插值，轨迹平滑
        try:
            # 1. 移到滑块中心
            page.mouse.move(start_x, start_y, steps=_random.randint(5, 8))
            time.sleep(_random.uniform(0.15, 0.3))

            # 2. 按下
            page.mouse.down()
            time.sleep(_random.uniform(0.05, 0.12))

            # 3. 平滑拖到终点（几乎水平，极小 y 偏移）
            # 分 2 段：加速段 + 减速段
            mid_x = start_x + (end_x - start_x) * _random.uniform(0.55, 0.7)
            mid_y = start_y + _random.uniform(-0.5, 0.5)

            # 加速段：步数少，移动快
            page.mouse.move(mid_x, mid_y, steps=_random.randint(12, 18))
            time.sleep(_random.uniform(0.01, 0.03))

            # 减速段：步数多，移动慢
            final_y = start_y + _random.uniform(-0.3, 0.3)
            page.mouse.move(end_x, final_y, steps=_random.randint(18, 28))
            time.sleep(_random.uniform(0.05, 0.1))

            # 4. 松开
            page.mouse.up()
        except Exception as exc:
            logger.info("[paypal_ddc] drag exception: %s", exc)
            continue
        # 等待验证通过
        slider_gone = False
        for _ in range(8):
            time.sleep(0.8)
            if _is_ddc_blocked_page(page):
                logger.info("[paypal_ddc] blocked page after slider drag (attempt %d)", attempt + 1)
                slider_gone = True
                break
            if not _ddc_slider_visible(page):
                slider_gone = True
                break
            cur = page.url
            if any(kw in cur for kw in ("/webapps/hermes", "checkoutweb", "/signin", "chatgpt.com")):
                logger.info("[paypal_ddc] slider passed → %s", cur[:80])
                return True

        if slider_gone:
            # 滑块消失后等待足够久让 blocked 页面充分渲染（DataDome blocked
            # 页面渲染可能需要 5-8 秒，分多次检查而不是一次性等待）
            for _check_i in range(4):
                time.sleep(2.0)
                if _is_ddc_blocked_page(page):
                    logger.info("[paypal_ddc] confirmed blocked page after slider gone (%d, attempt %d)",
                               _check_i + 1, attempt + 1)
                    return False
                cur = page.url
                if any(kw in cur for kw in ("/webapps/hermes", "checkoutweb", "/signin", "chatgpt.com")):
                    logger.info("[paypal_ddc] slider passed → %s", cur[:80])
                    return True
                if page.query_selector('input[name="login_email"]') or \
                   page.query_selector('#consentButton') or \
                   page.query_selector('[data-testid="email"]') or \
                   page.query_selector('[data-testid="createAccount"]'):
                    logger.info("[paypal_ddc] slider passed (page elements visible, attempt %d)", attempt + 1)
                    return True
            # 8 秒都没出现 blocked 也没出现表单 → 当做通过
            logger.info("[paypal_ddc] slider passed (no blocked after 8s, attempt %d)", attempt + 1)
            return True

        logger.info("[paypal_ddc] attempt %d failed (slider still visible), retrying...", attempt + 1)
        time.sleep(_random.uniform(1.0, 2.0))
    return False


def _wait_ddc_pass(page, *, timeout_seconds: int = 50, on_progress=None, max_blocked_retries: int = 4) -> bool:
    """等待 DataDome 自然通过或尝试解滑块。返回 True 表示通过。

    当滑块拖动后出现 blocked 页面或 invisible DDC 超时时，自动刷新重试
    （最多 max_blocked_retries 次）。
    """
    import random as _random

    blocked_retries = 0

    def _attempt_once() -> bool | None:
        """单次尝试。返回 True=通过, False=确认失败, None=blocked 需要重试。"""
        # 先等 3 秒让 DDC JS 自行跑完
        time.sleep(3)

        # 检测 blocked 页面（可能上一轮刷新后立即进入 blocked）
        if _is_ddc_blocked_page(page):
            logger.info("[paypal_ddc] blocked page detected on entry")
            return None

        # 检测可见滑块
        if _ddc_slider_visible(page):
            logger.info("[paypal_ddc] visible slider detected, attempting drag solver...")
            _emit_progress(on_progress, _progress_event("paypal_ddc_slider_detected"))
            solved = _try_solve_ddc_slider(page, attempts=2)
            if solved:
                # 确认真正通过（非 blocked）
                time.sleep(1)
                if _is_ddc_blocked_page(page):
                    logger.info("[paypal_ddc] slider solved but got blocked page")
                    return None
                return True
            # 滑块没解开，检查是否是 blocked
            if _is_ddc_blocked_page(page):
                return None
            logger.info("[paypal_ddc] drag solver failed")
            return False

        # 检测隐形 DDC iframe（JS 验证中，等待自动通过）
        if _has_ddc_iframe(page):
            logger.info("[paypal_ddc] invisible DDC challenge detected, waiting...")
            _emit_progress(on_progress, _progress_event("paypal_ddc_invisible_wait"))
            deadline = time.time() + min(timeout_seconds, 25)  # 隐形验证最多等 25 秒，不值得等太久
            while time.time() < deadline:
                time.sleep(2)
                # blocked 检测
                if _is_ddc_blocked_page(page):
                    logger.info("[paypal_ddc] blocked page during invisible wait")
                    return None
                cur = page.url
                # 页面已跳转说明通过
                if any(kw in cur for kw in ["/signin", "/authflow", "/webapps/hermes",
                                             "/pay", "chatgpt.com", "/checkoutweb"]):
                    logger.info("[paypal_ddc] DDC passed → %s", cur[:80])
                    return True
                # 检测到 PayPal 表单元素
                if page.query_selector('input[name="login_email"]') or \
                   page.query_selector('#consentButton') or \
                   page.query_selector('[data-testid="email"]'):
                    logger.info("[paypal_ddc] DDC passed (page elements visible)")
                    return True
                # 中途升级为可见滑块
                if _ddc_slider_visible(page):
                    logger.info("[paypal_ddc] upgraded to visible slider during wait")
                    solved = _try_solve_ddc_slider(page, attempts=2)
                    if solved:
                        time.sleep(1)
                        if _is_ddc_blocked_page(page):
                            return None
                        return True
                    if _is_ddc_blocked_page(page):
                        return None
                    return False
                # 重试按钮
                retry_btn = page.query_selector('button:has-text("重试")') or \
                            page.query_selector('button:has-text("Retry")')
                if retry_btn:
                    try:
                        if retry_btn.is_visible():
                            logger.info("[paypal_ddc] clicking retry button...")
                            retry_btn.click()
                            time.sleep(3)
                    except Exception:
                        pass
            logger.info("[paypal_ddc] DDC wait timeout (%ds), will retry via refresh", timeout_seconds)
            return None  # 超时 → 刷新重试（刷新后可能出现可拖的 slider）

        # 没有 DDC iframe 也没有滑块 → 自然通过
        return True

    # ── 主循环：blocked 时刷新重试 ──
    while True:
        result = _attempt_once()
        if result is True:
            return True
        if result is False:
            return False
        # result is None → blocked，刷新重试
        blocked_retries += 1
        if blocked_retries > max_blocked_retries:
            logger.info("[paypal_ddc] blocked page persists after %d retries, giving up", max_blocked_retries)
            _emit_progress(on_progress, _progress_event(
                "paypal_ddc_blocked_final",
                f"DataDome blocked 页面重试 {max_blocked_retries} 次仍未通过",
            ))
            return False
        logger.info("[paypal_ddc] blocked page detected, refreshing (retry %d/%d)...", blocked_retries, max_blocked_retries)
        _emit_progress(on_progress, _progress_event(
            "paypal_ddc_blocked_retry",
            f"DataDome 封锁页面，正在刷新重试 ({blocked_retries}/{max_blocked_retries})",
        ))
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            logger.info("[paypal_ddc] reload failed: %s", exc)
        time.sleep(_random.uniform(3.0, 5.0))


def _visible_locator_in_frames(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 1000):
    helper = getattr(api, "_visible_locator_in_frames", None)
    if callable(helper):
        return helper(selectors, timeout_ms=timeout_ms)
    return None


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
    if _dispatch_locator_value(locator, value):
        return True
    try:
        locator.click(timeout=1200)
    except Exception:
        pass
    try:
        locator.fill(value, timeout=1500)
        return True
    except Exception:
        return False


def _set_paypal_state_locator_value(locator, value: str, *, country: str = "") -> bool:
    normalized_country = _normalize_paypal_country(country)
    candidates = _jp_prefecture_candidates(value) if normalized_country == "JP" else [str(value or "").strip()]
    if not candidates:
        return False
    try:
        tag_name = str(locator.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag_name = ""
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
        if _set_locator_value(locator, candidate):
            return True
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
        locator.type(str(value or ""), delay=8, timeout=6000)
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
        tag_name = str(locator.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag_name = ""
    if tag_name == "select":
        try:
            text = str(locator.evaluate("el => el.selectedOptions && el.selectedOptions[0] ? (el.selectedOptions[0].textContent || '') : ''") or "").strip()
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


def _value_matches(expected: str, actual: str) -> bool:
    expected_raw = str(expected or "").strip()
    actual_raw = str(actual or "").strip()
    if expected_raw == actual_raw:
        return True
    expected_norm = re.sub(r"\s+", " ", expected_raw).lower()
    actual_norm = re.sub(r"\s+", " ", actual_raw).lower()
    return bool(expected_norm) and expected_norm == actual_norm


def _normalize_us_state_value(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    if not normalized:
        return ""
    upper = normalized.upper()
    if upper in US_STATE_CODE_TO_NAME:
        return upper
    return US_STATE_NAME_TO_CODE.get(normalized, upper)


def _jp_prefecture_candidates(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    normalized = re.sub(r"\s+", "-", raw).strip().lower()
    candidates = [raw]
    mapped = JP_PREFECTURE_NAME_TO_JA.get(normalized) or JP_PREFECTURE_NAME_TO_JA.get(normalized.replace("-to", ""))
    if mapped:
        candidates.append(mapped)
        candidates.append(mapped.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"))
    elif raw in JP_PREFECTURE_NAME_TO_JA.values():
        candidates.append(raw.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"))
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        item = str(item or "").strip()
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _normalize_jp_prefecture_value(value: str) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return ""
    lowered = raw.lower().replace(" ", "-")
    if lowered in JP_PREFECTURE_NAME_TO_JA:
        return JP_PREFECTURE_NAME_TO_JA[lowered]
    if raw in JP_PREFECTURE_NAME_TO_JA.values():
        return raw
    for ja in JP_PREFECTURE_NAME_TO_JA.values():
        if raw == ja.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"):
            return ja
    return raw


def _state_value_matches(expected: str, actual: str) -> bool:
    expected_jp = _normalize_jp_prefecture_value(expected)
    actual_jp = _normalize_jp_prefecture_value(actual)
    if expected_jp and actual_jp and expected_jp == actual_jp:
        return True
    expected_state = _normalize_us_state_value(expected)
    actual_state = _normalize_us_state_value(actual)
    if expected_state and actual_state and expected_state == actual_state:
        return True
    return _value_matches(expected, actual)


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
    if field == "state":
        return _state_value_matches(expected, actual)
    return _value_matches(expected, actual)


def _set_verified_locator_value(locator, value: str, *, field: str = "") -> bool:
    def matches() -> bool:
        actual = _read_locator_value(locator)
        return _field_value_matches(value, actual, field=field)

    # 优先使用 dispatch（React-native setter），最快；其次 fill，最后逐字 type
    for setter in (_dispatch_locator_value, _set_locator_value, _type_locator_value):
        if setter(locator, value):
            time.sleep(0.15)
            if matches():
                return True
    return False


def _body_excerpt(api: ChatGPTTeamAPI, limit: int = 2000):
    chunks: list[str] = []
    try:
        text = str(api.page.locator("body").inner_text(timeout=1500) or "").strip()
        if text:
            chunks.append(text)
    except Exception:
        pass
    for frame in _iter_page_frames(api):
        try:
            if frame is getattr(api.page, "main_frame", None):
                continue
            text = str(frame.locator("body").inner_text(timeout=700) or "").strip()
            if text and text not in chunks:
                chunks.append(text)
        except Exception:
            continue
    return "\n".join(chunks)[:limit]


def _compact_log_text(text: Any, *, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


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


def _paypal_otp_lock_key(phone: str) -> str:
    return _normalize_paypal_phone(phone)


def _acquire_paypal_otp_phone_lock(
    phone: str,
    *,
    on_progress=None,
    timeout_seconds: int = PAYPAL_OTP_PHONE_LOCK_TIMEOUT_SECONDS,
) -> str:
    key = _paypal_otp_lock_key(phone)
    if not key:
        return ""
    with _PAYPAL_OTP_LOCK_GUARD:
        lock = _PAYPAL_OTP_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PAYPAL_OTP_LOCKS[key] = lock
    _emit_progress(
        on_progress,
        _progress_event("paypal_otp_phone_lock_wait", phone=phone, phone_key=key),
    )
    acquired = lock.acquire(timeout=max(1, int(timeout_seconds)))
    if not acquired:
        _emit_progress(
            on_progress,
            _progress_event("paypal_otp_phone_lock_timeout", phone=phone, phone_key=key, level="warn"),
        )
        return ""
    _emit_progress(
        on_progress,
        _progress_event("paypal_otp_phone_lock_acquired", phone=phone, phone_key=key),
    )
    return key


def _release_paypal_otp_phone_lock(key: str, *, on_progress=None) -> None:
    normalized_key = _paypal_otp_lock_key(key)
    if not normalized_key:
        return
    lock = _PAYPAL_OTP_LOCKS.get(normalized_key)
    if not lock:
        return
    try:
        lock.release()
    except RuntimeError:
        return
    _emit_progress(
        on_progress,
        _progress_event("paypal_otp_phone_lock_released", phone_key=normalized_key),
    )


def _release_paypal_signup_phone_lock(state: dict[str, Any], *, on_progress=None) -> None:
    lock_key = str(state.get("otp_phone_lock_key") or "").strip()
    if not lock_key:
        return
    _release_paypal_otp_phone_lock(lock_key, on_progress=on_progress)
    state["otp_phone_lock_key"] = ""


def _ensure_paypal_signup_phone_lock(
    state: dict[str, Any],
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    if state.get("otp_phone_lock_key"):
        return True, ""
    phone = str(signup_profile.get("phone") or "")
    if not _paypal_otp_lock_key(phone):
        return True, ""
    key = _acquire_paypal_otp_phone_lock(phone, on_progress=on_progress)
    if not key:
        return False, "等待当前手机号验证码流程释放超时"
    state["otp_phone_lock_key"] = key
    return True, ""


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


def _normalize_paypal_country(value: str = "") -> str:
    normalized = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    return normalized[:2] or "US"


def _normalize_paypal_lang(value: str = "", country: str = "US") -> str:
    normalized = re.sub(r"[^A-Za-z-]", "", str(value or "")).lower()
    if normalized:
        return normalized.split("-", 1)[0] or PAYPAL_COUNTRY_DEFAULT_LANG.get(country, "en")
    return PAYPAL_COUNTRY_DEFAULT_LANG.get(country, "en")


def _force_paypal_us_locale(api: ChatGPTTeamAPI, *, country: str = "US", lang: str = "en") -> bool:
    current_url = str(getattr(api.page, "url", "") or "")
    if not _is_paypal_host(current_url):
        return False
    try:
        parsed = urlsplit(current_url)
    except Exception:
        return False
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    country = _normalize_paypal_country(country)
    lang = _normalize_paypal_lang(lang, country)
    locale = f"{lang}_{country}"
    changed = False
    if query.get("country.x") != country:
        query["country.x"] = country
        changed = True
    if query.get("locale.x") != locale:
        query["locale.x"] = locale
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
        logger.info("[paypal_bind_executor] forcing PayPal locale failed: %s", exc)
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


def _fast_autofill_checkout_fields(api: ChatGPTTeamAPI, fields: dict[str, str]) -> list[str]:
    fast_fields = {
        key: str(value or "")
        for key, value in (fields or {}).items()
        if key != "country" and key in AUTOFILL_FAST_SELECTORS and str(value or "").strip()
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
    for frame in _iter_page_frames(api):
        missing = {key: value for key, value in fast_fields.items() if key not in filled}
        if not missing:
            break
        try:
            result = frame.evaluate(script, {"fields": missing, "selectors": AUTOFILL_FAST_SELECTORS})
        except Exception:
            continue
        for key in result or []:
            if str(key) in missing:
                filled.add(str(key))
    return list(filled)


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
    fast_attempted = set(_fast_autofill_checkout_fields(api, dict(ordered_fields)))
    fast_verified = {
        key
        for key in fast_attempted
        if _checkout_value_matches(key, str(fields.get(key) or ""), _read_checkout_field_value(api, key))
    }
    for key, value in ordered_fields:
        if key in fast_verified:
            filled.append(key)
            continue
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
    if key == "state":
        return _state_value_matches(expected_text, actual_text)
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
        return False, "账单地址缺少国家/地址/城市/州/邮编"

    last_values: dict[str, str] = {}
    for attempt in range(1, 9):
        _suppress_address_autocomplete_ui(api)
        autofill_checkout_fields(api, billing_payload, on_progress=on_progress)
        time.sleep(0.25)
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
        time.sleep(0.25)

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


def _wait_for_paypal_checkout_interactive(api: ChatGPTTeamAPI, *, timeout_seconds: int = 45) -> bool:
    deadline = time.time() + max(5, timeout_seconds)
    while time.time() < deadline:
        if _visible_locator_in_frames(api, PAYPAL_CHECKOUT_SELECTORS, timeout_ms=800):
            return True
        if _visible_locator_in_frames(api, CHECKOUT_SUBMIT_SELECTORS, timeout_ms=500):
            return True
        body_text = _body_excerpt(api, 2000).strip()
        body_lower = body_text.lower()
        if body_text and (
            "paypal" in body_lower
            or "payment method" in body_lower
            or "payment details" in body_lower
            or "something went wrong" in body_lower
            or "unable to load" in body_lower
            or "支付" in body_text
        ):
            return True
        try:
            api.page.wait_for_timeout(1000)
        except Exception:
            time.sleep(1.0)
    logger.info(
        "[paypal_bind_executor] checkout page not interactive: url=%s body=%s",
        _safe_url_summary(getattr(api.page, "url", "")),
        _body_excerpt(api, 500),
    )
    return False


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
    if not _wait_for_paypal_checkout_interactive(api):
        _capture_screenshot(api, session_id, "paypal-checkout-not-interactive", screenshot_paths)
        return _build_result(
            "failed",
            failure_stage="open_checkout",
            message="打开 PayPal checkout 页面失败: checkout 页面未加载到可交互状态",
            screenshot_paths=screenshot_paths,
        )

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
        if locator.is_disabled(timeout=300):
            return False
    except Exception:
        pass
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
        if bool(api.page.evaluate(script)):
            return True
    except Exception:
        pass
    text_row_script = """() => {
      const paypalText = /(^|\\s)paypal(\\s|$)/i;
      const visible = (el) => {
        if (!el || !el.isConnected) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.pointerEvents === 'none') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const checked = (root) => {
        const radio = root?.querySelector?.('input[type="radio"]') || (root?.matches?.('input[type="radio"]') ? root : null);
        const roleRadio = root?.matches?.('[role="radio"]') ? root : root?.querySelector?.('[role="radio"]');
        return Boolean(radio?.checked)
          || String(roleRadio?.getAttribute?.('aria-checked') || '').toLowerCase() === 'true';
      };
      const clickLikeUser = (el) => {
        if (!el || !visible(el)) return false;
        el.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = el.getBoundingClientRect();
        const x = rect.left + Math.min(Math.max(rect.width / 2, 8), Math.max(rect.width - 8, 8));
        const y = rect.top + Math.min(Math.max(rect.height / 2, 8), Math.max(rect.height - 8, 8));
        const target = document.elementFromPoint(x, y) || el;
        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
          target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window }));
        }
        if (target !== el) el.click();
        return true;
      };
      const nodes = Array.from(document.querySelectorAll('label,button,[role="radio"],[role="button"],input[type="radio"],div,span'));
      for (const node of nodes) {
        const text = String(node.innerText || node.textContent || node.getAttribute?.('aria-label') || '').trim();
        const alt = String(node.getAttribute?.('alt') || node.querySelector?.('img[alt]')?.getAttribute('alt') || '').trim();
        if (!paypalText.test(text) && !paypalText.test(alt)) continue;
        const chain = [];
        let current = node;
        for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
          chain.push(current);
        }
        const target = chain.find((el) => {
          if (!visible(el)) return false;
          if (el.matches('label,button,[role="radio"],[role="button"]')) return true;
          if (el.querySelector('input[type="radio"],[role="radio"],button')) return true;
          const rect = el.getBoundingClientRect();
          return rect.width >= 160 && rect.height >= 28;
        });
        if (!target) continue;
        const radio = target.querySelector?.('input[type="radio"]') || chain.find((el) => el.matches?.('input[type="radio"]'));
        if (radio) {
          radio.click();
          if (!radio.checked) clickLikeUser(target);
        } else {
          clickLikeUser(target);
        }
        return checked(target) || checked(target.parentElement) || true;
      }
      return false;
    }"""
    for frame in _iter_page_frames(api):
        try:
            if bool(frame.evaluate(text_row_script)):
                return True
        except Exception:
            continue
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
    ssl_protocol_error_refreshes = 0
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        current_url = getattr(api.page, "url", "")
        body_text = _body_excerpt(api)
        if _is_paypal_ssl_protocol_error_page(current_url, body_text):
            if ssl_protocol_error_refreshes >= PAYPAL_SSL_PROTOCOL_ERROR_MAX_REFRESHES:
                _capture_screenshot(api, session_id, "paypal-ssl-protocol-error", screenshot_paths)
                _emit_progress(
                    on_progress,
                    _progress_event(
                        "paypal_ssl_protocol_error_retry_queued",
                        refreshes=ssl_protocol_error_refreshes,
                        url=current_url,
                        level="warn",
                    ),
                )
                return _build_result(
                    "failed",
                    failure_stage="paypal_ssl_protocol_error",
                    message="已提交 checkout，但 PayPal SSL_PROTOCOL_ERROR 刷新 2 次后仍无法进入 PayPal 页，加入待重试池",
                    screenshot_paths=screenshot_paths,
                )
            ssl_protocol_error_refreshes += 1
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_ssl_protocol_error_refresh",
                    refresh=ssl_protocol_error_refreshes,
                    max_refreshes=PAYPAL_SSL_PROTOCOL_ERROR_MAX_REFRESHES,
                    wait_seconds=PAYPAL_SSL_PROTOCOL_ERROR_REFRESH_INTERVAL_SECONDS,
                    url=current_url,
                    level="warn",
                ),
            )
            time.sleep(PAYPAL_SSL_PROTOCOL_ERROR_REFRESH_INTERVAL_SECONDS)
            try:
                api.page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logger.info("[paypal_bind_executor] PayPal SSL error page reload failed: %s", exc)
            time.sleep(1.0)
            continue
        if _is_paypal_host(current_url):
            if _force_paypal_us_locale(api):
                current_url = getattr(api.page, "url", "")
            _emit_progress(on_progress, _progress_event("paypal_authorize", url=current_url))
            return None

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
        if _click_first(api, CHECKOUT_SUBMIT_SELECTORS, timeout_ms=1200):
            _emit_progress(
                on_progress,
                _progress_event("paypal_wait_redirect", attempt=attempts, url=current_url),
            )
            time.sleep(1.0)
            _select_chatgpt_account_if_needed(api, email=email)
        else:
            time.sleep(0.35)

    _capture_screenshot(api, session_id, "paypal-submit-timeout", screenshot_paths)
    return _build_result(
        "failed",
        failure_stage="submit_checkout",
        message="提交订阅后未跳转到 PayPal 授权页",
        screenshot_paths=screenshot_paths,
    )


def _inspect_paypal_page(api: ChatGPTTeamAPI) -> dict[str, Any]:
    current_url = getattr(api.page, "url", "")
    body_text = _body_excerpt(api, 8000)
    body_lower = body_text.lower()
    is_paypal_page = _is_paypal_host(current_url)
    if is_paypal_page:
        _ensure_paypal_hosted_captcha_bypass(api)
    phone_rejected_prompt = _has_paypal_phone_rejected_prompt(api) if is_paypal_page else False
    if phone_rejected_prompt and not any(hint in body_lower for hint in PAYPAL_PHONE_REJECTED_HINTS):
        body_text = f"{body_text}\nTry a different phone number"
        body_lower = body_text.lower()
    card_rejected_prompt = is_paypal_page and any(hint in body_lower for hint in PAYPAL_CARD_REJECTED_HINTS)

    email_locator = _visible_locator_in_frames(api, PAYPAL_EMAIL_SELECTORS, timeout_ms=400)
    password_locator = _visible_locator_in_frames(api, PAYPAL_PASSWORD_SELECTORS, timeout_ms=400)
    approve_locator = _visible_locator_in_frames(api, PAYPAL_APPROVE_SELECTORS, timeout_ms=400)
    prompt_locator = _visible_locator_in_frames(api, PAYPAL_DISMISS_PROMPT_SELECTORS, timeout_ms=400)
    create_account_locator = _visible_locator_in_frames(api, PAYPAL_CREATE_ACCOUNT_SELECTORS, timeout_ms=400)
    phone_locator = _visible_locator_in_frames(api, PAYPAL_PHONE_SELECTORS, timeout_ms=400)
    card_locator = _visible_locator_in_frames(api, PAYPAL_CARD_NUMBER_SELECTORS, timeout_ms=400)
    otp_inputs_ready = _has_paypal_otp_inputs(api) if is_paypal_page else False
    registration_text_hint = is_paypal_page and (
        ("card number" in body_lower and "billing address" in body_lower)
        or ("create password" in body_lower and "agree & create account" in body_lower)
        or ("pay with debit or credit card" in body_lower and "create password" in body_lower)
    )

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
    registration_inputs_ready = bool(card_locator or phone_locator or registration_text_hint)
    otp_text_hint = any(
        hint in body_lower
        for hint in (
            "enter your code",
            "enter the code",
            "enter code",
            "we sent a 6-digit code",
            "sent a 6-digit code",
            "6-digit code",
            "verification code",
            "security code",
            "code was sent",
            "check your phone",
            "验证码",
        )
    )
    if otp_text_hint:
        otp_inputs_ready = True
    needs_otp = is_paypal_page and (
        otp_inputs_ready or otp_text_hint
    )
    registration_ready = is_paypal_page and not otp_inputs_ready and registration_inputs_ready
    if card_rejected_prompt:
        registration_ready = True
    return {
        "url": current_url,
        "body_text": body_text,
        "needs_login": needs_login,
        "login_phase": login_phase,
        "has_passkey_prompt": has_passkey_prompt,
        "approve_ready": approve_ready,
        "create_account_ready": bool(create_account_locator),
        "registration_ready": registration_ready,
        "registration_text_hint": registration_text_hint,
        "card_rejected": card_rejected_prompt,
        "needs_otp": needs_otp,
        "otp_inputs_ready": otp_inputs_ready,
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


def _click_paypal_phone_rejected_ok_in_frame(frame) -> bool:
    script = r"""
    () => {
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
      };
      const textOf = (el) => (el && (el.innerText || el.textContent || el.value || '') || '').replace(/\s+/g, ' ').trim();
      const rejected = (text) => /try a different phone number|unable to complete your request|別の電話番号|リクエストを完了できません/i.test(text || '');
      const roots = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]'))
        .filter((node) => visible(node) && rejected(textOf(node)));
      if (!roots.length && !rejected(textOf(document.body))) return false;
      const searchRoots = roots.length ? roots : [document.body];
      for (const root of searchRoots) {
        const controls = Array.from(root.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]'))
          .filter(visible);
        const ok = controls.find((node) => /^(ok|okay|close)$/i.test(textOf(node))) || controls.find((node) => /ok|close/i.test(textOf(node)));
        if (ok) {
          ok.click();
          return true;
        }
      }
      return false;
    }
    """
    try:
        return bool(frame.evaluate(script))
    except Exception:
        return False


def _dismiss_paypal_phone_rejected_prompt(api: ChatGPTTeamAPI) -> bool:
    for frame in _iter_page_frames(api):
        if _click_paypal_phone_rejected_ok_in_frame(frame):
            time.sleep(1.0)
            if not _has_paypal_phone_rejected_prompt(api):
                return True
    for _ in range(3):
        if _click_first(api, PAYPAL_DISMISS_PROMPT_SELECTORS, timeout_ms=1200):
            time.sleep(0.8)
            if not _has_paypal_phone_rejected_prompt(api):
                return True
        try:
            api.page.keyboard.press("Escape")
            time.sleep(0.5)
            if not _has_paypal_phone_rejected_prompt(api):
                return True
        except Exception:
            return False
    return not _has_paypal_phone_rejected_prompt(api)


def _has_paypal_phone_rejected_prompt(api: ChatGPTTeamAPI) -> bool:
    if _visible_locator_in_frames(api, PAYPAL_PHONE_REJECTED_SELECTORS, timeout_ms=500):
        return True
    try:
        text = _body_excerpt(api, 12000).lower()
    except Exception:
        text = ""
    return bool(text) and any(hint in text for hint in PAYPAL_PHONE_REJECTED_HINTS)


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
    normalized_country = _normalize_paypal_country(country)
    country_labels = {
        "JP": ("Japan", "日本"),
        "US": ("United States", "United States of America"),
    }
    fallback_options = ["US", "United States", "United States of America"]
    options = [normalized_country]
    options.extend(country_labels.get(normalized_country, ()))
    if normalized_country != "US":
        options.extend(fallback_options)
    for option in options:
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


def _fill_paypal_signup_visible_form(api: ChatGPTTeamAPI, signup_profile: dict[str, str | bool]) -> dict[str, Any]:
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
    if _normalize_paypal_country(str(payload.get("country") or "")) == "JP":
        payload["birth_date"] = str(signup_profile.get("birth_date") or signup_profile.get("birthDate") or DEFAULT_PAYPAL_JP_BIRTH_DATE).strip()
        payload["native_first_name"] = str(
            signup_profile.get("native_first_name")
            or signup_profile.get("nativeFirstName")
            or DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME
        ).strip()
        payload["native_last_name"] = str(
            signup_profile.get("native_last_name")
            or signup_profile.get("nativeLastName")
            or DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME
        ).strip()
    script = r"""(profile) => {
      const values = profile || {};
      const filled = [];
      const missing = [];
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const digits = (value) => String(value || '').replace(/\D+/g, '');
      const usStates = {
        alabama: 'AL', alaska: 'AK', arizona: 'AZ', arkansas: 'AR', california: 'CA', colorado: 'CO',
        connecticut: 'CT', delaware: 'DE', florida: 'FL', georgia: 'GA', hawaii: 'HI', idaho: 'ID',
        illinois: 'IL', indiana: 'IN', iowa: 'IA', kansas: 'KS', kentucky: 'KY', louisiana: 'LA',
        maine: 'ME', maryland: 'MD', massachusetts: 'MA', michigan: 'MI', minnesota: 'MN',
        mississippi: 'MS', missouri: 'MO', montana: 'MT', nebraska: 'NE', nevada: 'NV',
        'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
        'north carolina': 'NC', 'north dakota': 'ND', ohio: 'OH', oklahoma: 'OK', oregon: 'OR',
        pennsylvania: 'PA', 'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD',
        tennessee: 'TN', texas: 'TX', utah: 'UT', vermont: 'VT', virginia: 'VA',
        washington: 'WA', 'west virginia': 'WV', wisconsin: 'WI', wyoming: 'WY',
      };
      const normalizeState = (value) => {
        const text = normalize(value);
        if (!text) return '';
        const upper = text.toUpperCase();
        return /^[A-Z]{2}$/.test(upper) ? upper : (usStates[text] || upper);
      };
      const textAround = (el) => {
        const parts = [
          el.id,
          el.name,
          el.type,
          el.autocomplete,
          el.placeholder,
          el.getAttribute('aria-label'),
        ];
        if (el.id) {
          document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach((label) => parts.push(label.innerText));
        }
        let node = el;
        for (let depth = 0; depth < 4 && node; depth += 1) {
          parts.push(node.innerText);
          node = node.parentElement;
        }
        return normalize(parts.filter(Boolean).join(' '));
      };
      const directText = (el) => {
        const parts = [
          el.id,
          el.name,
          el.type,
          el.autocomplete,
          el.placeholder,
          el.getAttribute('aria-label'),
        ];
        if (el.id) {
          document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach((label) => parts.push(label.innerText));
        }
        const parent = el.parentElement;
        if (parent) {
          const label = parent.querySelector(':scope > label, :scope > span, :scope > div');
          if (label) parts.push(label.innerText || label.textContent);
        }
        return normalize(parts.filter(Boolean).join(' '));
      };
      const controls = Array.from(document.querySelectorAll('input, select, textarea'))
        .filter((el) => isVisible(el) && !el.disabled && !el.readOnly);
      const controlCandidates = () => controls.map((el) => ({
        el,
        direct: directText(el),
        text: textAround(el),
        tag: String(el.tagName || '').toLowerCase(),
        type: String(el.type || '').toLowerCase(),
        rect: el.getBoundingClientRect(),
      }));
      const setValue = (el, value) => {
        if (!el || value === undefined || value === null || String(value).trim() === '') return false;
        const tag = String(el.tagName || '').toLowerCase();
        if (tag === 'select') {
          const wanted = String(value).trim().toLowerCase();
          const option = Array.from(el.options || []).find((opt) => {
            const optValue = String(opt.value || '').trim().toLowerCase();
            const optText = String(opt.textContent || '').trim().toLowerCase();
            return optValue === wanted || optText === wanted || optText.includes(wanted);
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
        el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: String(value) }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
      };
      const findControl = (field) => {
        const candidates = controlCandidates();
        const by = (predicate) => candidates.find(predicate)?.el || null;
        if (field === 'country') return by((c) => c.tag === 'select' && /country|region/.test(c.text));
        if (field === 'email') return by((c) => c.type === 'email' || /\bemail\b/.test(c.text));
        if (field === 'phone') return by((c) => c.tag !== 'select' && /phone number|mobile number|telephone|phone|電話番号|電話|携帯電話|携帯/.test(c.text) && !/phone type/.test(c.text));
        if (field === 'card_number') return by((c) => /card number|cc-number|cardnumber/.test(c.text));
        if (field === 'card_expiry') return by((c) => /expiration|expiry|exp date|cc-exp/.test(c.text));
        if (field === 'card_cvv') return by((c) => /cvv|cvc|security code|cc-csc/.test(c.text));
        if (field === 'password') return by((c) => c.type === 'password' || /create password|password/.test(c.text));
        if (field === 'first_name') return by((c) => /first name|given-name|firstname/.test(c.text));
        if (field === 'last_name') return by((c) => /last name|family-name|lastname/.test(c.text));
        if (field === 'address1') return by((c) => /street address|address line 1|address-line1|address1/.test(c.text));
        if (field === 'city') return by((c) => /\bcity\b|address-level2/.test(c.text));
        if (field === 'state') return by((c) => /\bstate\b|address-level1/.test(c.text));
        if (field === 'zip') return by((c) => /zip code|postal code|postcode|postal-code|\bzip\b/.test(c.text));
        if (field === 'birth_date') {
          return (
            by((c) => c.tag !== 'select' && /date of birth|birth date|birthday|dob|生年月日|年\/月\/日/.test(c.direct))
            || by((c) => c.tag !== 'select' && /date of birth|birth date|birthday|dob|生年月日|年\/月\/日/.test(c.text))
          );
        }
        return null;
      };
      const valueMatches = (field, actual, expected) => {
        if (!expected) return true;
        if (field === 'birth_date') {
          return digits(actual) === digits(expected);
        }
        if (['phone', 'card_number', 'card_cvv'].includes(field)) {
          const actualDigits = digits(actual);
          const expectedDigits = digits(expected);
          return Boolean(expectedDigits) && (actualDigits === expectedDigits || actualDigits.endsWith(expectedDigits));
        }
        if (field === 'card_expiry') {
          const actualDigits = digits(actual).slice(-4);
          const expectedDigits = digits(expected).slice(-4);
          return Boolean(expectedDigits) && actualDigits === expectedDigits;
        }
        if (field === 'state') {
          return normalizeState(actual) === normalizeState(expected);
        }
        return normalize(actual) === normalize(expected);
      };
      const order = ['country', 'email', 'phone', 'card_number', 'card_expiry', 'card_cvv', 'first_name', 'last_name', 'address1', 'city', 'state', 'zip', 'password'];
      for (const field of order) {
        const expected = values[field];
        if (!expected) continue;
        const control = findControl(field);
        if (!control) {
          missing.push(field);
          continue;
        }
        const actual = control.value || control.textContent || '';
        if (!valueMatches(field, actual, expected)) {
          if (setValue(control, expected)) filled.push(field);
        }
      }
      const country = normalize(values.country);
      const needsJpExtras = ['jp', 'japan', '日本'].includes(country);
      if (needsJpExtras) {
        const birthControl = findControl('birth_date');
        if (!birthControl) {
          missing.push('birth_date');
        } else if (!valueMatches('birth_date', birthControl.value || birthControl.textContent || '', values.birth_date)) {
          if (setValue(birthControl, values.birth_date)) filled.push('birth_date');
        }
        const firstControl = findControl('first_name');
        const lastControl = findControl('last_name');
        const minTop = Math.max(
          firstControl ? firstControl.getBoundingClientRect().bottom : 0,
          lastControl ? lastControl.getBoundingClientRect().bottom : 0
        );
        const nativeInputs = controlCandidates()
          .filter((c) => c.tag !== 'select' && c.el !== firstControl && c.el !== lastControl)
          .filter((c) => c.rect.top > minTop + 8)
          .filter((c) => /(^|\s)(名|姓)(\s|$)|漢字|かな|カナ|名前/.test(c.text))
          .sort((a, b) => (a.rect.top - b.rect.top) || (a.rect.left - b.rect.left))
          .map((c) => c.el);
        const nativeFirst = nativeInputs[0] || null;
        const nativeLast = nativeInputs[1] || null;
        if (!nativeFirst) {
          missing.push('native_first_name');
        } else if (!valueMatches('native_first_name', nativeFirst.value || nativeFirst.textContent || '', values.native_first_name)) {
          if (setValue(nativeFirst, values.native_first_name)) filled.push('native_first_name');
        }
        if (!nativeLast) {
          missing.push('native_last_name');
        } else if (!valueMatches('native_last_name', nativeLast.value || nativeLast.textContent || '', values.native_last_name)) {
          if (setValue(nativeLast, values.native_last_name)) filled.push('native_last_name');
        }
      }
      const required = ['email', 'phone', 'card_number', 'card_expiry', 'card_cvv', 'first_name', 'last_name', 'address1', 'city', 'state', 'zip', 'password'];
      const stillMissing = [];
      for (const field of required) {
        const expected = values[field];
        const control = findControl(field);
        const actual = control ? (control.value || control.textContent || '') : '';
        if (!control || !valueMatches(field, actual, expected)) stillMissing.push(field);
      }
      if (needsJpExtras) {
        const birthControl = findControl('birth_date');
        if (!birthControl || !valueMatches('birth_date', birthControl.value || birthControl.textContent || '', values.birth_date)) stillMissing.push('birth_date');
        const firstControl = findControl('first_name');
        const lastControl = findControl('last_name');
        const minTop = Math.max(
          firstControl ? firstControl.getBoundingClientRect().bottom : 0,
          lastControl ? lastControl.getBoundingClientRect().bottom : 0
        );
        const nativeInputs = controlCandidates()
          .filter((c) => c.tag !== 'select' && c.el !== firstControl && c.el !== lastControl)
          .filter((c) => c.rect.top > minTop + 8)
          .filter((c) => /(^|\s)(名|姓)(\s|$)|漢字|かな|カナ|名前/.test(c.text))
          .sort((a, b) => (a.rect.top - b.rect.top) || (a.rect.left - b.rect.left))
          .map((c) => c.el);
        const nativeFirst = nativeInputs[0] || null;
        const nativeLast = nativeInputs[1] || null;
        if (!nativeFirst || !valueMatches('native_first_name', nativeFirst.value || nativeFirst.textContent || '', values.native_first_name)) stillMissing.push('native_first_name');
        if (!nativeLast || !valueMatches('native_last_name', nativeLast.value || nativeLast.textContent || '', values.native_last_name)) stillMissing.push('native_last_name');
      }
      return { filled, missing, stillMissing };
    }"""
    best_result: dict[str, Any] | None = None
    last_error = ""
    for frame in _iter_page_frames(api):
        try:
            result = frame.evaluate(script, payload)
            if not isinstance(result, dict):
                continue
            if not result.get("stillMissing"):
                return result
            score = len(result.get("filled") or []) - len(result.get("stillMissing") or [])
            best_score = -10_000
            if best_result is not None:
                best_score = len(best_result.get("filled") or []) - len(best_result.get("stillMissing") or [])
            if best_result is None or score > best_score:
                best_result = result
        except Exception as exc:
            last_error = str(exc)
    if best_result is not None:
        return best_result
    return {"filled": [], "missing": ["dom"], "stillMissing": ["dom"], "error": last_error}


def _fill_paypal_signup_form(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    _emit_progress(on_progress, _progress_event("paypal_fill_signup", url=getattr(api.page, "url", "")))
    _set_paypal_country(api, str(signup_profile.get("country") or "US"))
    # email 在第一步可能已提交（输入框不再可见），标记为可选跳过
    _OPTIONAL_SKIP_FIELDS = {"email"}
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
            if key in _OPTIONAL_SKIP_FIELDS:
                continue
            return False, f"{label} 为空"
        locator = _visible_locator_in_frames(api, selectors, timeout_ms=1200)
        if locator is None:
            # 邮箱在第一步已填写，第二步不可见时跳过
            if key in _OPTIONAL_SKIP_FIELDS:
                logger.info("[paypal_signup] field '%s' not visible, skipping (likely already submitted)", key)
                continue
            return False, f"未找到 {label} 输入框"
        if not _set_verified_locator_value(locator, value, field=key):
            actual = _read_locator_value(locator)
            return False, f"{label} 填写后校验失败: 期望={value!r}, 实际={actual!r}"
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
        locator = _visible_locator_in_frames(api, selectors, timeout_ms=1200)
        if locator is None:
            return False, f"未找到 {label} 输入框"
        if key == "state":
            country = str(signup_profile.get("country") or "US")
            did_set = _set_paypal_state_locator_value(locator, value, country=country)
            time.sleep(0.15)
            verified = _field_value_matches(value, _read_locator_value(locator), field=key)
        else:
            did_set = _set_verified_locator_value(locator, value, field=key)
            verified = did_set
        if not did_set or not verified:
            actual = _read_locator_value(locator)
            return False, f"{label} 填写后校验失败: 期望={value!r}, 实际={actual!r}"
        field_locators[key] = locator
        if key == "address1":
            _dismiss_address_autocomplete(api, locator)
            time.sleep(0.15)

    _dismiss_address_autocomplete(api, field_locators.get("address1"))
    for key, selectors, expected, label in address_fields:
        locator = field_locators.get(key)
        actual = _read_locator_value(locator)
        if _field_value_matches(expected, actual, field=key):
            continue
        if key == "state":
            rewritten = _set_paypal_state_locator_value(locator, expected, country=str(signup_profile.get("country") or "US"))
        else:
            rewritten = _set_locator_value(locator, expected)
        if not rewritten:
            return False, f"{label} 自动补全后被改写，且重写失败"
        if key == "address1":
            _dismiss_address_autocomplete(api, locator)
        time.sleep(0.15)
        actual = _read_locator_value(locator)
        if not _field_value_matches(expected, actual, field=key):
            return False, f"{label} 自动补全后校验失败: 期望={expected!r}, 实际={actual!r}"

    if _normalize_paypal_country(str(signup_profile.get("country") or "")) == "JP":
        birth_date = str(
            signup_profile.get("birth_date")
            or signup_profile.get("birthDate")
            or DEFAULT_PAYPAL_JP_BIRTH_DATE
        ).strip()
        birth_locator = _visible_locator_in_frames(api, PAYPAL_BIRTH_DATE_SELECTORS, timeout_ms=1200)
        if birth_locator is None:
            logger.info("[paypal_signup] JP birth date input not found by direct selectors; DOM fallback will try")
        else:
            _set_locator_value(birth_locator, birth_date)
            time.sleep(0.2)
            actual_birth = _read_locator_value(birth_locator)
            if re.sub(r"\D+", "", actual_birth) != re.sub(r"\D+", "", birth_date):
                return False, f"PayPal 生年月日填写后校验失败: 期望={birth_date!r}, 实际={actual_birth!r}"

    dom_result = _fill_paypal_signup_visible_form(api, signup_profile)
    still_missing = [str(item) for item in dom_result.get("stillMissing") or [] if str(item) and str(item) not in _OPTIONAL_SKIP_FIELDS]
    if still_missing:
        logger.info(
            "[paypal_bind_executor] PayPal signup DOM validation could not confirm fields: %s",
            ", ".join(still_missing),
        )
    if _normalize_paypal_country(str(signup_profile.get("country") or "")) == "JP":
        jp_missing = [field for field in ("birth_date", "native_first_name", "native_last_name") if field in still_missing]
        if jp_missing:
            return False, f"PayPal 日区注册字段填写后校验失败: {', '.join(jp_missing)}"
    return True, ""


def _paypal_signup_visible_validation_error(api: ChatGPTTeamAPI) -> str:
    text = _body_excerpt(api, 12000)
    lowered = text.lower()
    hints = (
        "正しい日付を入力してください",
        "漢字を使用してください",
        "入力内容を確認してください",
        "please enter a valid date",
        "please check your information",
    )
    matched = [hint for hint in hints if hint.lower() in lowered]
    return " / ".join(matched)


def _fill_paypal_otp_inputs(api: ChatGPTTeamAPI, otp_code: str) -> bool:
    digits = re.sub(r"\D+", "", str(otp_code or ""))[:8]
    if len(digits) < 5:
        return False
    script = """(code) => {
      const digits = String(code || '').replace(/\\D+/g, '').slice(0, 8).split('');
      if (digits.length < 5) return { filled: false, count: 0 };
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const pageText = String(document.body?.innerText || '').toLowerCase();
      const otpDialog = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]')).find((node) => {
        const text = String(node.innerText || '').toLowerCase();
        return isVisible(node) && (text.includes('enter your code') || text.includes('6-digit code') || text.includes('verification code'));
      });
      const root = otpDialog || document;
      const visibleInputs = Array.from(root.querySelectorAll('input, [role="textbox"], [contenteditable="true"]')).filter((node) => {
        return isVisible(node);
      });
      const candidates = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || '').toLowerCase();
        const auto = String(node.autocomplete || '').toLowerCase();
        const name = String(node.name || '').toLowerCase();
        const id = String(node.id || '').toLowerCase();
        const aria = String(node.getAttribute('aria-label') || '').toLowerCase();
        const placeholder = String(node.placeholder || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        const identity = `${name} ${id} ${aria} ${placeholder}`;
        const mentionsOtp = (
          identity.includes('otp') ||
          identity.includes('one-time') ||
          identity.includes('one time') ||
          identity.includes('verification code') ||
          identity.includes('security code') ||
          identity.includes('验证码')
        );
        return (
          auto === 'one-time-code' ||
          (mentionsOtp && mode === 'numeric') ||
          (mentionsOtp && type === 'tel') ||
          (mentionsOtp && maxLength >= 1) ||
          (mentionsOtp && maxLength === -1)
        );
      });
      const oneCharInputs = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        return maxLength === 1 && (mode === 'numeric' || type === 'tel' || type === 'text' || !type);
      });
      const visualOtpInputs = visibleInputs.filter((node) => {
        const rect = node.getBoundingClientRect();
        const maxLength = Number(node.maxLength || 0);
        return rect.width >= 20 && rect.width <= 90 && rect.height >= 20 && rect.height <= 90 && rect.left >= 0 && rect.top >= 0 && (maxLength <= 1 || maxLength === -1);
      });
      const rows = [];
      visualOtpInputs.sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        return (ar.top - br.top) || (ar.left - br.left);
      }).forEach((node) => {
        const rect = node.getBoundingClientRect();
        let row = rows.find((entry) => Math.abs(entry.top - rect.top) <= 12);
        if (!row) {
          row = { top: rect.top, nodes: [] };
          rows.push(row);
        }
        row.nodes.push(node);
      });
      const visualRow = rows
        .map((row) => row.nodes.slice().sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left))
        .find((nodes) => nodes.length >= digits.length && nodes.length <= 8);
      const dialogInputs = otpDialog && visibleInputs.length >= digits.length && visibleInputs.length <= 8 ? visibleInputs : [];
      const groupedOneCharInputs = oneCharInputs.length >= digits.length ? oneCharInputs : (visualRow || dialogInputs);
      const targets = groupedOneCharInputs.length >= digits.length ? groupedOneCharInputs : candidates;
      const orderedTargets = targets.slice().sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        return (ar.top - br.top) || (ar.left - br.left);
      });
      if (orderedTargets.length >= digits.length) {
        orderedTargets.slice(0, digits.length).forEach((node, index) => {
          node.focus();
          if ('value' in node) node.value = digits[index];
          else node.textContent = digits[index];
          node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: digits[index] }));
          node.dispatchEvent(new Event('change', { bubbles: true }));
          node.dispatchEvent(new Event('blur', { bubbles: true }));
        });
        const verified = orderedTargets.slice(0, digits.length).every((node, index) => String(('value' in node ? node.value : node.textContent) || '') === digits[index]);
        return { filled: verified, count: verified ? digits.length : 0 };
      }
      const single = candidates[0] || document.querySelector('input[autocomplete=\"one-time-code\"]');
      if (!single) {
        const boxes = (visualRow || []).slice(0, digits.length).map((node) => {
          const rect = node.getBoundingClientRect();
          return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        });
        return { filled: false, count: boxes.length, boxes };
      }
      single.focus();
      if ('value' in single) single.value = digits.join('');
      else single.textContent = digits.join('');
      single.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: digits.join('') }));
      single.dispatchEvent(new Event('change', { bubbles: true }));
      single.dispatchEvent(new Event('blur', { bubbles: true }));
      return { filled: String(('value' in single ? single.value : single.textContent) || '').replace(/\\D+/g, '').startsWith(digits.join('')), count: 1 };
    }"""
    deadline = time.time() + 12
    while time.time() < deadline:
        for frame in _iter_page_frames(api):
            try:
                result = frame.evaluate(script, digits)
            except Exception:
                continue
            if isinstance(result, dict) and result.get("filled"):
                return True
            if result is True:
                return True
            if isinstance(result, dict) and result.get("boxes"):
                boxes = [box for box in result.get("boxes") or [] if isinstance(box, dict)]
                try:
                    if boxes:
                        first = boxes[0]
                        api.page.mouse.click(float(first["x"]), float(first["y"]))
                        api.page.keyboard.type(digits, delay=50)
                        time.sleep(0.5)
                        return True
                except Exception:
                    pass
                try:
                    for index, box in enumerate(boxes[: len(digits)]):
                        api.page.mouse.click(float(box["x"]), float(box["y"]))
                        api.page.keyboard.type(digits[index], delay=30)
                    time.sleep(0.5)
                    return True
                except Exception:
                    pass
            try:
                locator = frame.locator('[role="dialog"] input, [aria-modal="true"] input, .modal input, [class*="modal" i] input, [role="dialog"] [role="textbox"], [aria-modal="true"] [role="textbox"]').first
                if locator.is_visible(timeout=250):
                    locator.click(timeout=1000)
                    locator.type(digits, delay=40, timeout=5000)
                    return True
            except Exception:
                pass
        try:
            body_text = _body_excerpt(api, 2000).lower()
        except Exception:
            body_text = ""
        if "enter your code" in body_text or "6-digit code" in body_text:
            try:
                viewport = api.page.viewport_size or {"width": 1280, "height": 800}
            except Exception:
                viewport = {"width": 1280, "height": 800}
            try:
                # The PayPal OTP modal renders six unlabeled boxes in the lower-middle of the viewport.
                api.page.mouse.click(float(viewport["width"]) * 0.39, float(viewport["height"]) * 0.79)
                api.page.keyboard.type(digits, delay=50)
                time.sleep(0.3)
                return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def _has_paypal_otp_inputs(api: ChatGPTTeamAPI) -> bool:
    script = """() => {
      const visibleInputs = Array.from(document.querySelectorAll('input')).filter((node) => {
        return Boolean(node.offsetParent || node.getClientRects?.().length);
      });
      const oneCharInputs = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        return maxLength === 1 && (mode === 'numeric' || type === 'tel' || type === 'text' || !type);
      });
      if (oneCharInputs.length >= 4 && oneCharInputs.length <= 8) return true;
      const candidates = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || '').toLowerCase();
        const auto = String(node.autocomplete || '').toLowerCase();
        const name = String(node.name || '').toLowerCase();
        const id = String(node.id || '').toLowerCase();
        const aria = String(node.getAttribute('aria-label') || '').toLowerCase();
        const placeholder = String(node.placeholder || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        const identity = `${name} ${id} ${aria} ${placeholder}`;
        const mentionsOtp = (
          identity.includes('otp') ||
          identity.includes('one-time') ||
          identity.includes('one time') ||
          identity.includes('verification code') ||
          identity.includes('security code') ||
          identity.includes('验证码')
        );
        return (
          auto === 'one-time-code' ||
          (mentionsOtp && mode === 'numeric') ||
          (mentionsOtp && type === 'tel') ||
          (mentionsOtp && maxLength >= 1) ||
          (mentionsOtp && maxLength === -1)
        );
      });
      return candidates.length > 0;
    }"""
    try:
        return bool(api.page.evaluate(script))
    except Exception:
        return False


def _click_paypal_create_account(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    if _click_first(api, PAYPAL_CREATE_ACCOUNT_SELECTORS, timeout_ms=2000):
        _emit_progress(on_progress, _progress_event("paypal_create_account", url=getattr(api.page, "url", "")))
        return True
    return False


def _is_paypal_pay_entry_url(url: str) -> bool:
    try:
        parsed = urlsplit(str(url or ""))
    except Exception:
        return False
    return _is_paypal_host(url) and parsed.path.rstrip("/").lower() == "/pay"


def _paypal_signup_email_step_advanced(api: ChatGPTTeamAPI, before_url: str) -> bool:
    """Return True once PayPal advances from the /pay email gate."""
    _sync_relevant_payment_page(api, prefer_paypal=True)
    current_url = str(getattr(api.page, "url", "") or "")
    if current_url and current_url != before_url:
        return True
    if _is_paypal_pay_entry_url(before_url) and not _is_paypal_pay_entry_url(current_url):
        return True
    state = _inspect_paypal_page(api)
    return bool(state.get("registration_ready") or state.get("registration_text_hint") or state.get("needs_otp"))


def _wait_paypal_signup_email_step_advanced(api: ChatGPTTeamAPI, before_url: str, *, timeout_seconds: float = 8.0) -> bool:
    deadline = time.time() + max(1.0, float(timeout_seconds))
    while time.time() < deadline:
        if _paypal_signup_email_step_advanced(api, before_url):
            return True
        try:
            api.page.wait_for_timeout(400)
        except Exception:
            time.sleep(0.4)
    return _paypal_signup_email_step_advanced(api, before_url)


def _js_click_paypal_signup_email_submit(api: ChatGPTTeamAPI) -> bool:
    script = r"""
    () => {
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const textOf = (node) => String(node.innerText || node.textContent || node.value || node.getAttribute?.('aria-label') || '')
        .replace(/\s+/g, ' ')
        .trim();
      const controls = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"]'))
        .filter(visible);
      const preferred = [
        /continue to payment/i,
        /^continue$/i,
        /^next$/i,
        /create (an )?account/i,
        /sign up/i,
        /注册|创建账户|建立账户|建立帳戶/,
      ];
      for (const pattern of preferred) {
        const node = controls.find((candidate) => pattern.test(textOf(candidate)));
        if (node) {
          node.click();
          return { clicked: true, text: textOf(node).slice(0, 120) };
        }
      }

      const emailInput = Array.from(document.querySelectorAll(
        'input#email, input[name="email"], input[name="login_email"], input[type="email"], input[autocomplete="username"]'
      )).find(visible);
      const form = emailInput?.closest?.('form') || document.querySelector('form');
      const formControls = form
        ? Array.from(form.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]')).filter(visible)
        : [];
      const enabled = (node) => !(
        node.disabled ||
        node.getAttribute?.('disabled') !== null ||
        node.getAttribute?.('aria-disabled') === 'true'
      );
      const fallbackButton = formControls.find((node) => enabled(node) && (
        String(node.getAttribute?.('type') || '').toLowerCase() === 'submit' ||
        node.tagName === 'BUTTON' ||
        node.getAttribute?.('role') === 'button'
      ));
      if (fallbackButton) {
        fallbackButton.click();
        return { clicked: true, text: (textOf(fallbackButton).slice(0, 120) || 'form-button-click') };
      }
      return { clicked: false, text: '' };
    }
    """
    for frame in _iter_page_frames(api):
        try:
            result = frame.evaluate(script)
            if isinstance(result, dict) and result.get("clicked"):
                logger.info("[paypal_signup] JS email submit clicked: %s", result.get("text"))
                return True
            if result is True:
                return True
        except Exception:
            continue
    return False


def _js_recover_paypal_email_spinner(api: ChatGPTTeamAPI, email: str) -> dict[str, Any]:
    """在不刷新页面的情况下，用 JS 清除 PayPal SPA 的 spinner/loading 状态并重新提交邮箱。

    PayPal SPA 在 Camoufox 下有时邮箱提交后卡在 spinner，但 DOM 仍然存在。
    此函数尝试：
    1. 移除所有 spinner/loading overlay 元素
    2. 移除 disabled/aria-busy 属性
    3. 重新填入邮箱（确保值没丢）
    4. 重新点击 submit 按钮
    5. 如果找不到 submit 按钮则直接提交 form

    返回 dict: {recovered: bool, detail: str}
    """
    script = r"""
    (email) => {
      const result = {recovered: false, detail: '', spinners_removed: 0, submit_clicked: false};
      try {
        // Step 1: 移除所有 spinner/loading/overlay 元素
        const spinnerSelectors = [
          '.spinner', '.loading', '.loader', '[class*="spinner"]', '[class*="loading"]',
          '[class*="Spinner"]', '[class*="Loading"]', '[class*="loader"]', '[class*="Loader"]',
          '[data-testid*="spinner"]', '[data-testid*="loading"]',
          '.vx_overlay', '[class*="overlay"]', '[class*="Overlay"]',
          '[aria-label*="loading" i]', '[aria-label*="spinner" i]',
          '[role="progressbar"]', '[role="status"][aria-busy="true"]',
        ];
        spinnerSelectors.forEach(sel => {
          document.querySelectorAll(sel).forEach(node => {
            try {
              // 不移除 captcha overlay
              if (node.id && /captcha/i.test(node.id)) return;
              if (node.className && /captcha/i.test(String(node.className))) return;
              node.remove();
              result.spinners_removed++;
            } catch(e) {}
          });
        });

        // Step 2: 移除 disabled/aria-busy 属性
        document.querySelectorAll('[disabled], [aria-disabled="true"], [aria-busy="true"]').forEach(node => {
          try {
            node.removeAttribute('disabled');
            node.removeAttribute('aria-disabled');
            node.removeAttribute('aria-busy');
          } catch(e) {}
        });

        // Step 3: 找到邮箱输入框并确保值正确
        const emailSelectors = ['input#email', 'input[name="email"]', 'input[type="email"]',
          'input[autocomplete="email"]', 'input[id*="email" i]', 'input[name*="email" i]'];
        let emailInput = null;
        for (const sel of emailSelectors) {
          const node = document.querySelector(sel);
          if (node && node.offsetParent !== null) {
            emailInput = node;
            break;
          }
        }
        if (emailInput) {
          // 用 native setter 设置值，触发 React/Vue 的 onChange
          const nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
          )?.set;
          if (nativeSet) {
            nativeSet.call(emailInput, email);
          } else {
            emailInput.value = email;
          }
          emailInput.dispatchEvent(new Event('input', {bubbles: true}));
          emailInput.dispatchEvent(new Event('change', {bubbles: true}));
          result.detail += 'email_set;';
        } else {
          result.detail += 'no_email_input;';
        }

        // Step 4: 找到 submit 按钮并点击
        const visible = (node) => {
          if (!node) return false;
          const style = window.getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const textOf = (node) => String(node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
        const controls = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]'))
          .filter(visible);
        const submitPatterns = [
          /^next$/i, /^continue$/i, /continue to payment/i,
          /create (an )?account/i, /sign up/i, /注册|创建账户|建立账户/,
        ];
        let submitBtn = null;
        for (const pattern of submitPatterns) {
          submitBtn = controls.find(n => pattern.test(textOf(n)));
          if (submitBtn) break;
        }
        if (!submitBtn) {
          // fallback: type=submit 的按钮
          submitBtn = controls.find(n => n.getAttribute('type') === 'submit');
        }
        if (submitBtn) {
          submitBtn.removeAttribute('disabled');
          submitBtn.removeAttribute('aria-disabled');
          submitBtn.click();
          result.submit_clicked = true;
          result.detail += 'btn_clicked:' + textOf(submitBtn).slice(0, 40) + ';';
        } else {
          // fallback: 直接 submit form
          const form = document.querySelector('form');
          if (form) {
            if (typeof form.requestSubmit === 'function') form.requestSubmit();
            else form.submit();
            result.submit_clicked = true;
            result.detail += 'form_submitted;';
          } else {
            result.detail += 'no_submit_target;';
          }
        }

        result.recovered = result.submit_clicked;
      } catch(e) {
        result.detail += 'error:' + String(e).slice(0, 100);
      }
      return result;
    }
    """
    try:
        value = api.page.evaluate(script, email)
        if isinstance(value, dict):
            return value
        return {"recovered": False, "detail": f"unexpected_return:{value}"}
    except Exception as exc:
        return {"recovered": False, "detail": f"evaluate_error:{exc}"}


def _inspect_paypal_email_gate(api: ChatGPTTeamAPI) -> dict[str, Any]:
    script = r"""
    () => {
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const textOf = (node) => String(node.innerText || node.textContent || node.value || node.getAttribute?.('aria-label') || '')
        .replace(/\s+/g, ' ')
        .trim();
      const controls = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"]'))
        .filter(visible)
        .slice(0, 20)
        .map((node) => ({
          tag: node.tagName,
          id: node.id || '',
          type: node.getAttribute('type') || '',
          text: textOf(node).slice(0, 120),
          disabled: Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true'),
        }));
      const forms = Array.from(document.querySelectorAll('form')).slice(0, 5).map((form) => ({
        id: form.id || '',
        action: form.getAttribute('action') || '',
        method: form.getAttribute('method') || '',
      }));
      const inputs = Array.from(document.querySelectorAll('input')).filter(visible).slice(0, 20).map((node) => ({
        id: node.id || '',
        name: node.name || '',
        type: node.type || '',
        valueLen: String(node.value || '').length,
        autocomplete: node.autocomplete || '',
      }));
      return { controls, forms, inputs, title: document.title || '' };
    }
    """
    try:
        value = api.page.evaluate(script)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def _submit_paypal_signup_email_step(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    on_progress=None,
) -> tuple[bool, str]:
    email = str(signup_profile.get("email") or "").strip()
    if not email:
        return False, "PayPal 注册邮箱为空"
    email_locator = state.get("email_locator")
    if not email_locator:
        return False, "未找到 PayPal 注册邮箱输入框"
    if not _set_locator_value(email_locator, email):
        return False, "填写 PayPal 注册邮箱失败"
    _emit_progress(on_progress, _progress_event("paypal_signup_email", url=getattr(api.page, "url", "")))
    before_url = str(getattr(api.page, "url", "") or "")
    submit_clicked = False
    if _click_first(api, PAYPAL_SIGNUP_EMAIL_SUBMIT_SELECTORS, timeout_ms=2500):
        submit_clicked = True
        if _wait_paypal_signup_email_step_advanced(api, before_url, timeout_seconds=6.0):
            return True, ""
        logger.info(
            "[paypal_signup] email submit clicked but page did not advance (SPA may be stuck), "
            "treating as submitted to allow stuck-recovery: before=%s current=%s",
            _safe_url_summary(before_url),
            _safe_url_summary(getattr(api.page, "url", "")),
        )
        return True, ""
    else:
        try:
            email_locator.press("Enter", timeout=1200)
            submit_clicked = True
        except Exception:
            pass
    if _wait_paypal_signup_email_step_advanced(api, before_url, timeout_seconds=4.0):
        return True, ""
    try:
        email_locator.press("Enter", timeout=1200)
        submit_clicked = True
    except Exception:
        pass
    if _wait_paypal_signup_email_step_advanced(api, before_url, timeout_seconds=4.0):
        return True, ""
    if _js_click_paypal_signup_email_submit(api):
        submit_clicked = True
        if _wait_paypal_signup_email_step_advanced(api, before_url, timeout_seconds=6.0):
            return True, ""
    # 提交按钮已被点击但页面没有明显 advance（Camoufox SPA 可能卡住）
    # → 仍然返回 True，让上层 stuck 检测 + reload/goto 机制来恢复
    if submit_clicked:
        logger.info(
            "[paypal_signup] email submit clicked but page did not advance (SPA may be stuck), "
            "treating as submitted to allow stuck-recovery: before=%s current=%s",
            _safe_url_summary(before_url),
            _safe_url_summary(getattr(api.page, "url", "")),
        )
        return True, ""
    logger.info(
        "[paypal_signup] email submit did not advance: before=%s current=%s gate=%s body=%s",
        _safe_url_summary(before_url),
        _safe_url_summary(getattr(api.page, "url", "")),
        _compact_log_text(_inspect_paypal_email_gate(api), limit=500),
        _compact_log_text(_body_excerpt(api, 500), limit=220),
    )
    return False, "PayPal 注册邮箱提交后未跳转到注册表单"


def _replace_paypal_signup_phone(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    phone = str(signup_profile.get("phone") or "").strip()
    if not phone:
        return False, "PayPal 注册手机号为空"
    ok, locator = _set_first_visible_value_with_locator(api, PAYPAL_PHONE_SELECTORS, phone)
    if not ok or locator is None:
        return False, "未找到 PayPal 注册手机号输入框"
    if not _set_verified_locator_value(locator, phone, field="phone"):
        actual = _read_locator_value(locator)
        return False, f"PayPal 注册手机号替换后校验失败: 期望={phone!r}, 实际={actual!r}"
    _emit_progress(
        on_progress,
        _progress_event(
            "paypal_replace_signup_phone",
            url=getattr(api.page, "url", ""),
            phone=phone,
        ),
    )
    return True, ""


def _replace_paypal_signup_card(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    card_number = _generate_paypal_card_number()
    card_expiry = _generate_paypal_card_expiry()
    card_cvv = _generate_paypal_card_cvv(card_number)
    signup_profile["card_number"] = card_number
    signup_profile["card_expiry"] = card_expiry
    signup_profile["card_cvv"] = card_cvv
    _emit_progress(
        on_progress,
        _progress_event(
            "paypal_card_rejected_retry",
            url=getattr(api.page, "url", ""),
        ),
    )
    fields = [
        ("card_number", PAYPAL_CARD_NUMBER_SELECTORS, card_number, "PayPal 卡号"),
        ("card_expiry", PAYPAL_CARD_EXPIRY_SELECTORS, card_expiry, "PayPal 卡有效期"),
        ("card_cvv", PAYPAL_CARD_CVV_SELECTORS, card_cvv, "PayPal 卡 CVV"),
    ]
    for key, selectors, value, label in fields:
        ok, locator = _set_first_visible_value_with_locator(api, selectors, value)
        if not ok or locator is None:
            return False, f"未找到 {label} 输入框"
        if not _set_verified_locator_value(locator, value, field=key):
            actual = _read_locator_value(locator)
            return False, f"{label} 替换后校验失败: 期望={value!r}, 实际={actual!r}"
    time.sleep(0.5)
    return True, ""


def _click_paypal_signup_otp_resend(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    script = r"""
    () => {
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const textOf = (node) => String((node && (node.innerText || node.textContent || node.value)) || '').replace(/\s+/g, ' ').trim();
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]'))
        .filter((node) => visible(node) && /enter your code|6-digit code|verification code/i.test(textOf(node)));
      const roots = dialogs.length ? dialogs : [document.body];
      for (const root of roots) {
        const controls = Array.from(root.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
          .filter(visible);
        const resend = controls.find((node) => /^resend$/i.test(textOf(node))) || controls.find((node) => /resend/i.test(textOf(node)));
        if (resend) {
          resend.click();
          return true;
        }
      }
      return false;
    }
    """
    for frame in _iter_page_frames(api):
        try:
            if frame.evaluate(script):
                _emit_progress(on_progress, _progress_event("paypal_otp_resend_clicked", url=getattr(api.page, "url", "")))
                time.sleep(1.0)
                return True
        except Exception:
            continue
    if _click_first(api, ['button:has-text("Resend")', 'a:has-text("Resend")', '[role="button"]:has-text("Resend")'], timeout_ms=1500):
        _emit_progress(on_progress, _progress_event("paypal_otp_resend_clicked", url=getattr(api.page, "url", "")))
        time.sleep(1.0)
        return True
    return False


def _poll_paypal_signup_otp(
    *,
    api: ChatGPTTeamAPI,
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
        timeout_seconds=min(PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS, max(60, int(timeout_seconds or PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS))),
        initial_delay_seconds=0,
        resend_after_seconds=PAYPAL_SIGNUP_OTP_RESEND_AFTER_SECONDS,
        max_resend_attempts=PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS,
        is_cancelled=is_cancelled,
        progress=_progress_adapter(on_progress),
    )
    setattr(provider, "_gopay_resend_callback", lambda: _click_paypal_signup_otp_resend(api, on_progress=on_progress))
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


def _wait_for_paypal_subscription_return(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int = PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
    is_cancelled=None,
    on_progress=None,
):
    deadline = time.time() + max(1, int(timeout_seconds or 0))
    _emit_progress(
        on_progress,
        _progress_event(
            "paypal_return_wait",
            url=getattr(api.page, "url", ""),
            timeout_seconds=int(timeout_seconds or 0),
        ),
    )
    while time.time() < deadline:
        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="post_submit", message="任务已取消", screenshot_paths=screenshot_paths)

        _sync_relevant_payment_page(api, prefer_paypal=False)
        current_url = getattr(api.page, "url", "")
        if _is_chatgpt_or_openai_return_url(current_url):
            try:
                remaining_ms = max(1000, int((deadline - time.time()) * 1000))
                api.page.wait_for_load_state("load", timeout=min(remaining_ms, 10000))
            except Exception:
                time.sleep(1.0)
                continue
            time.sleep(PAYPAL_APPROVE_RETURN_SETTLE_SECONDS)
            _emit_progress(
                on_progress,
                _progress_event("paypal_return_confirmed", url=current_url),
            )
            _capture_screenshot(api, session_id, "success", screenshot_paths)
            return _build_result(
                "success",
                failure_stage="",
                message="PayPal 授权后已回跳 ChatGPT/OpenAI 页面，确认绑定成功",
                screenshot_paths=screenshot_paths,
            )

        if _is_paypal_host(current_url):
            classified = classify_paypal_checkout_state(current_url, _body_excerpt(api))
            if classified and classified.get("status") in {"failed", "needs_review"}:
                _capture_screenshot(api, session_id, "paypal-authorize-failed", screenshot_paths)
                classified["screenshot_paths"] = screenshot_paths
                return classified
        time.sleep(1.0)

    _capture_screenshot(api, session_id, "paypal-return-timeout", screenshot_paths)
    return _build_result(
        "needs_review",
        failure_stage="paypal_return_timeout",
        message="PayPal 已授权，但 120 秒内未回跳 ChatGPT/OpenAI 页面，需要确认最终绑定状态",
        screenshot_paths=screenshot_paths,
    )


def _run_paypal_signup_flow(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    on_progress=None,
    is_cancelled=None,
) -> tuple[bool, str, bool]:
    current_url = getattr(api.page, "url", "")
    signup_submitted = bool(state.get("signup_submitted"))
    signup_email_submitted = bool(state.get("signup_email_submitted"))
    phone_only_retry = bool(state.get("phone_only_retry"))
    phone_key = _normalize_paypal_phone(str(signup_profile.get("phone") or ""))
    submitted_phone_keys = state.get("submitted_phone_keys")
    if not isinstance(submitted_phone_keys, set):
        submitted_phone_keys = set()
        state["submitted_phone_keys"] = submitted_phone_keys
    phone_already_submitted = bool(phone_key and phone_key in submitted_phone_keys)
    card_retry_count = int(state.get("card_retry_count") or 0)

    if phone_already_submitted and not signup_submitted:
        signup_submitted = True
        state["signup_submitted"] = True

    if signup_submitted:
        validation_error = _paypal_signup_visible_validation_error(api)
        if validation_error:
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            return False, f"PayPal 注册表单校验失败: {validation_error}", True
        if state.get("card_rejected"):
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            if card_retry_count >= 5:
                return False, "PayPal 连续拒绝卡片，已停止换卡重试", False
            ok, error = _replace_paypal_signup_card(api, signup_profile=signup_profile, on_progress=on_progress)
            if not ok:
                return False, error, True
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_submit_signup",
                    url=current_url,
                    phone=str(signup_profile.get("phone") or ""),
                ),
            )
            ok, error = _ensure_paypal_signup_phone_lock(
                state,
                signup_profile=signup_profile,
                on_progress=on_progress,
            )
            if not ok:
                return False, error, False
            if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
                _release_paypal_signup_phone_lock(state, on_progress=on_progress)
                return False, "未找到 PayPal 注册提交按钮", False
            state["signup_submitted"] = True
            state["signup_submitted_at"] = time.time()
            state["card_retry_count"] = card_retry_count + 1
            time.sleep(2.0)
            return True, "", True
        if not state.get("otp_inputs_ready") and not state.get("needs_otp"):
            submitted_at = float(state.get("signup_submitted_at") or 0)
            if submitted_at > 0 and time.time() - submitted_at > PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS:
                return False, "等待 PayPal 验证码超时", False
            if (
                state.get("approve_ready")
                and not state.get("registration_ready")
                and not state.get("registration_text_hint")
                and not state.get("needs_otp")
            ):
                # OTP 验证通过后出现 "Agree & Create Account" 按钮，直接点击完成注册
                logger.info(
                    "[paypal_signup] approve_ready after OTP, attempting PAYPAL_CREATE_SUBMIT click, url=%s",
                    current_url,
                )
                if _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=3000):
                    _emit_progress(
                        on_progress,
                        _progress_event("paypal_agree_create_clicked", url=current_url),
                    )
                    logger.info("[paypal_signup] Agree & Create Account clicked, waiting for navigation")
                    try:
                        api.page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    time.sleep(3.0)
                    return True, "", True
                # fallback: 退出 signup flow，让 authorize flow 处理
                logger.info("[paypal_signup] PAYPAL_CREATE_SUBMIT not found, falling back to authorize flow")
                return True, "", False
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_wait_signup_otp",
                    url=current_url,
                    otp_channel=str(signup_profile.get("otp_channel") or "sms"),
                    phone=str(signup_profile.get("phone") or ""),
                ),
            )
            time.sleep(1.5)
            return True, "", True
        try:
            otp = _poll_paypal_signup_otp(
                api=api,
                signup_profile=signup_profile,
                timeout_seconds=PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
            )
        except GoPayOTPCancelled as exc:
            return False, f"等待 PayPal OTP 超时: {exc}", False
        if not _fill_paypal_otp_inputs(api, otp):
            return False, "未找到 PayPal 验证码输入框", False
        _emit_progress(on_progress, _progress_event("paypal_submit_otp", url=current_url))
        if not _click_first(api, PAYPAL_NEXT_SELECTORS, timeout_ms=2500):
            try:
                api.page.keyboard.press("Enter")
            except Exception:
                return False, "未找到 PayPal 验证码提交按钮", False
        _release_paypal_signup_phone_lock(state, on_progress=on_progress)
        time.sleep(2.0)
        return True, "", True

    if phone_only_retry and (state.get("registration_ready") or state.get("registration_text_hint")):
        ok, error = _ensure_paypal_signup_phone_lock(
            state,
            signup_profile=signup_profile,
            on_progress=on_progress,
        )
        if not ok:
            return False, error, False
        ok, error = _replace_paypal_signup_phone(api, signup_profile=signup_profile, on_progress=on_progress)
        if not ok:
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            return False, error, True
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_submit_signup",
                url=current_url,
                phone=str(signup_profile.get("phone") or ""),
            ),
        )
        if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            return False, "未找到 PayPal 注册提交按钮", False
        state["signup_submitted"] = True
        state["signup_submitted_at"] = time.time()
        state["phone_only_retry"] = False
        if phone_key:
            submitted_phone_keys.add(phone_key)
        time.sleep(2.0)
        return True, "", True

    if state.get("create_account_ready") and _click_paypal_create_account(api, on_progress=on_progress):
        time.sleep(2.0)
        return True, "", True

    _is_email_step = (
        state.get("email_locator")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
    )
    # SPA 完全死锁：email_locator 消失但邮箱已提交且无任何表单元素
    _is_blank_after_email = (
        signup_email_submitted
        and not state.get("email_locator")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_login")
        and not state.get("needs_otp")
        and not state.get("approve_ready")
    )
    if _is_email_step or _is_blank_after_email:
        if signup_email_submitted:
            submitted_at = float(state.get("signup_email_submitted_at") or 0)
            # ── 总超时判断（跨 reload 周期累计） ──
            first_submitted_at = float(state.get("_email_first_submitted_at") or submitted_at)
            if not state.get("_email_first_submitted_at") and submitted_at > 0:
                state["_email_first_submitted_at"] = submitted_at
            if first_submitted_at > 0 and time.time() - first_submitted_at > PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS:
                return False, "等待 PayPal 注册表单加载超时", False

            # ── SPA 卡住恢复策略 ──
            # Camoufox 下 PayPal SPA 提交邮箱后可能出现内部状态死锁：
            #   - 没有 spinner DOM 元素（spinners_removed=0）
            #   - JS 注入重新提交表单无效（SPA 忽略）
            # 策略：先做 1 次 JS 快速尝试（~8s），若无效立即 reload
            # + 完整重置所有状态让流程从头走（email 输入→提交→等待表单）。
            # 允许最多 3 次 reload 周期（_email_reload_cycle_count）。
            _MAX_JS_BEFORE_RELOAD = 1   # 每个 reload 周期内最多 1 次 JS 尝试
            _MAX_RELOAD_CYCLES = 3      # 最多 reload 3 次
            elapsed = time.time() - submitted_at if submitted_at > 0 else 0
            js_count = int(state.get("_email_stuck_recover_count") or 0)
            reload_cycles = int(state.get("_email_reload_cycle_count") or 0)

            if (
                elapsed > PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS
                and (js_count <= _MAX_JS_BEFORE_RELOAD or reload_cycles < _MAX_RELOAD_CYCLES)
            ):
                if js_count < _MAX_JS_BEFORE_RELOAD:
                    # ── JS 快速尝试 ──
                    state["_email_stuck_recover_count"] = js_count + 1
                    recover_email = str(signup_profile.get("email") or "").strip()
                    logger.info(
                        "[paypal_signup] page stuck after email submit (%.0fs), JS recover attempt %d...",
                        elapsed, js_count + 1,
                    )
                    _emit_progress(on_progress, _progress_event(
                        "paypal_signup_email_reload",
                        f"邮箱提交后页面卡住，正在 JS 恢复 ({js_count + 1}/{_MAX_JS_BEFORE_RELOAD})",
                    ))
                    recover_result = _js_recover_paypal_email_spinner(api, recover_email)
                    logger.info("[paypal_signup] JS recover result: %s", recover_result)
                    if not recover_result.get("recovered"):
                        state["signup_email_submitted"] = False
                        state["signup_email_submitted_at"] = 0
                    time.sleep(2.0)
                    return True, "", True

                if reload_cycles < _MAX_RELOAD_CYCLES:
                    # ── Reload + 完整状态重置 ──
                    # JS 尝试用尽但 SPA 仍然死锁 → reload 让页面回到邮箱输入步骤，
                    # 完整重置所有邮箱提交相关状态以便从头走流程。
                    reload_cycles += 1
                    state["_email_reload_cycle_count"] = reload_cycles
                    # 重置本周期计数器，下一周期允许新的 JS 尝试
                    state["_email_stuck_recover_count"] = 0
                    state["_email_first_submitted_at"] = 0
                    state["signup_email_submitted"] = False
                    state["signup_email_submitted_at"] = 0
                    state["_fill_retry_count"] = 0
                    logger.info(
                        "[paypal_signup] SPA deadlocked after JS attempts, reload cycle %d/%d (%.0fs total)...",
                        reload_cycles, _MAX_RELOAD_CYCLES,
                        time.time() - first_submitted_at,
                    )
                    _emit_progress(on_progress, _progress_event(
                        "paypal_signup_email_reload",
                        f"邮箱提交后 SPA 死锁，正在刷新页面重试 (第 {reload_cycles}/{_MAX_RELOAD_CYCLES} 轮)",
                    ))
                    try:
                        api.page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    time.sleep(3.0)
                    return True, "", True

            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_wait_signup_form",
                    url=current_url,
                    email=str(signup_profile.get("email") or ""),
                ),
            )
            time.sleep(1.5)
            return True, "", True
        if _is_blank_after_email:
            # 页面完全空白（email_locator 消失），无法提交邮箱，等待 reload 恢复
            time.sleep(1.5)
            return True, "", True
        ok, error = _submit_paypal_signup_email_step(
            api,
            signup_profile=signup_profile,
            state=state,
            on_progress=on_progress,
        )
        if ok:
            state["signup_email_submitted"] = True
            state["signup_email_submitted_at"] = time.time()
        return ok, error, True

    if state.get("registration_ready") or state.get("registration_text_hint"):
        # 等待页面 DOM 完全渲染（邮箱提交后表单展开需要时间）
        try:
            api.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        time.sleep(1.5)
        ok, error = _ensure_paypal_signup_phone_lock(
            state,
            signup_profile=signup_profile,
            on_progress=on_progress,
        )
        if not ok:
            return False, error, False
        ok, error = _fill_paypal_signup_form(api, signup_profile=signup_profile, on_progress=on_progress)
        if not ok:
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            # 输入框可能还没渲染出来，允许重试（回到主循环等下一轮）
            fill_retry_count = int(state.get("_fill_retry_count") or 0)
            if fill_retry_count < 3:
                state["_fill_retry_count"] = fill_retry_count + 1
                logger.info("[paypal_signup] fill form failed (%s), will retry (%d/3)", error, fill_retry_count + 1)
                time.sleep(3.0)
                return True, "", True  # handled=True, 回到主循环下一轮重试
            return False, error, True
        state["_fill_retry_count"] = 0
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_submit_signup",
                url=current_url,
                phone=str(signup_profile.get("phone") or ""),
            ),
        )
        if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
            _release_paypal_signup_phone_lock(state, on_progress=on_progress)
            return False, "未找到 PayPal 注册提交按钮", False
        state["signup_submitted"] = True
        state["signup_submitted_at"] = time.time()
        if phone_key:
            submitted_phone_keys.add(phone_key)
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
    paypal_country: str = "US",
    paypal_lang: str = "en",
    is_cancelled=None,
    on_progress=None,
    phone_accounts: list[dict] | None = None,
):
    deadline = time.time() + max(20, timeout_seconds)
    paypal_country = _normalize_paypal_country(paypal_country)
    paypal_lang = _normalize_paypal_lang(paypal_lang, paypal_country)
    effective_credentials = dict(credentials or {})
    signup_profiles = _paypal_signup_profiles_for_phone_pool(signup_profile, phone_accounts)
    signup_profile_index = 0
    active_signup_profile = signup_profiles[signup_profile_index] if signup_profiles else (signup_profile or {})
    if paypal_mode == "create_account" and active_signup_profile:
        effective_credentials = {
            "email": str(active_signup_profile.get("email") or ""),
            "password": str(active_signup_profile.get("password") or ""),
        }
    signup_email_submitted = False
    signup_email_submitted_at = 0.0
    signup_form_submitted = False
    signup_submitted_at = 0.0
    phone_only_retry = False
    card_retry_count = 0
    submitted_phone_keys: set[str] = set()
    otp_phone_lock_key = ""
    last_ddc_check_at = 0.0
    ddc_blocked_refresh_count = 0
    state: dict[str, Any] = {}
    _MAX_DDC_BLOCKED_REFRESHES = 3
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        active_phone_key = _normalize_paypal_phone(str(active_signup_profile.get("phone") or ""))
        active_phone_submitted = bool(active_phone_key and active_phone_key in submitted_phone_keys)
        if not signup_form_submitted and not active_phone_submitted:
            _force_paypal_us_locale(api, country=paypal_country, lang=paypal_lang)
        current_url = getattr(api.page, "url", "")
        if current_url and not _is_paypal_host(current_url):
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            _emit_progress(on_progress, _progress_event("paypal_wait_result", url=current_url))
            return None
        _ensure_paypal_hosted_captcha_bypass(api)

        # DataDome DDC 检测：每轮都检查可见滑块 / blocked 页面，隐形 DDC iframe 做节流
        if _is_paypal_host(current_url):
            page = getattr(api, "page", None)
            if page:
                # 先检测 blocked 页面（滑块验证失败后可能停在此页面）
                if _is_ddc_blocked_page(page):
                    ddc_blocked_refresh_count += 1
                    if ddc_blocked_refresh_count > _MAX_DDC_BLOCKED_REFRESHES:
                        if otp_phone_lock_key:
                            _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                            otp_phone_lock_key = ""
                        return _build_result(
                            "failed",
                            failure_stage="paypal_datadome_blocked",
                            message=f"DataDome 封锁页面刷新 {_MAX_DDC_BLOCKED_REFRESHES} 次仍未恢复",
                            screenshot_paths=screenshot_paths,
                        )
                    logger.info("[paypal_authorize] blocked page detected in main loop, refreshing (%d/%d)...",
                               ddc_blocked_refresh_count, _MAX_DDC_BLOCKED_REFRESHES)
                    _emit_progress(on_progress, _progress_event(
                        "paypal_ddc_blocked_retry",
                        f"检测到 DataDome 封锁页面，正在刷新重试 ({ddc_blocked_refresh_count}/{_MAX_DDC_BLOCKED_REFRESHES})",
                    ))
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    time.sleep(4)
                    continue

                slider_visible = _ddc_slider_visible(page)
                # 可见滑块立即处理；不可见时每 15 秒探测一次隐形 iframe
                ddc_iframe_present = (
                    (not slider_visible)
                    and (time.time() - last_ddc_check_at > 15)
                    and _has_ddc_iframe(page)
                )
                if slider_visible or ddc_iframe_present:
                    last_ddc_check_at = time.time()
                    ddc_passed = _wait_ddc_pass(page, timeout_seconds=50, on_progress=on_progress)
                    if not ddc_passed:
                        if otp_phone_lock_key:
                            _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                            otp_phone_lock_key = ""
                        return _build_result(
                            "failed",
                            failure_stage="paypal_datadome_blocked",
                            message="DataDome 滑块/风控验证未通过",
                            screenshot_paths=screenshot_paths,
                        )

        if callable(is_cancelled) and is_cancelled():
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="post_submit", message="任务已取消", screenshot_paths=screenshot_paths)

        # 保留跨循环的恢复状态键（_inspect_paypal_page 每轮重建 state dict）
        _prev_recover_keys = {
            k: state[k] for k in (
                "_email_stuck_recover_count", "_email_reload_cycle_count",
                "_email_first_submitted_at", "_fill_retry_count",
            ) if k in state
        } if isinstance(state, dict) else {}
        state = _inspect_paypal_page(api)
        state.update(_prev_recover_keys)
        classified = classify_paypal_checkout_state(current_url, state.get("body_text", ""))
        if (
            paypal_mode == "create_account"
            and classified
            and classified.get("failure_stage") == "paypal_phone_rejected"
            and signup_profile_index + 1 < len(signup_profiles)
        ):
            rejected_profile = active_signup_profile
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_phone_rejected_waiting_dismiss",
                    phone_pool_index=signup_profile_index + 1,
                    phone_pool_total=len(signup_profiles),
                    rejected_phone=str(rejected_profile.get("phone") or ""),
                    url=current_url,
                    level="warn",
                ),
            )
            if not _dismiss_paypal_phone_rejected_prompt(api):
                time.sleep(1.0)
                continue
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            signup_profile_index += 1
            active_signup_profile = signup_profiles[signup_profile_index]
            signup_form_submitted = False
            signup_submitted_at = 0.0
            phone_only_retry = True
            card_retry_count = 0
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_phone_rejected_rotate",
                    phone_pool_index=signup_profile_index + 1,
                    phone_pool_total=len(signup_profiles),
                    rejected_phone=str(rejected_profile.get("phone") or ""),
                    next_phone=str(active_signup_profile.get("phone") or ""),
                    sms_url=_safe_url_summary(str(active_signup_profile.get("sms_url") or "")),
                    url=current_url,
                    level="warn",
                ),
            )
            time.sleep(1.5)
            continue
        if classified and classified.get("status") == "failed":
            # DataDome blocked → 刷新重试而不是直接退出（共用主循环计数器）
            if classified.get("failure_stage") == "paypal_datadome_blocked":
                ddc_blocked_refresh_count += 1
                if ddc_blocked_refresh_count <= _MAX_DDC_BLOCKED_REFRESHES:
                    page = getattr(api, "page", None)
                    if page:
                        logger.info("[paypal_authorize] classify detected datadome_blocked, refreshing (%d/%d)...",
                                   ddc_blocked_refresh_count, _MAX_DDC_BLOCKED_REFRESHES)
                        _emit_progress(on_progress, _progress_event(
                            "paypal_ddc_blocked_retry",
                            f"classify 检测到 DataDome 封锁，正在刷新重试 ({ddc_blocked_refresh_count}/{_MAX_DDC_BLOCKED_REFRESHES})",
                        ))
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass
                        time.sleep(4)
                        continue
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            if (
                paypal_mode == "create_account"
                and classified.get("failure_stage") == "paypal_phone_rejected"
            ):
                _emit_progress(
                    on_progress,
                    _progress_event(
                        "paypal_phone_rejected_final",
                        rejected_phone=str(active_signup_profile.get("phone") or ""),
                        phone_pool_index=signup_profile_index + 1,
                        phone_pool_total=len(signup_profiles),
                        url=current_url,
                        level="warn",
                    ),
                )
            _capture_screenshot(api, session_id, "paypal-authorize-failed", screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified
        if classified and classified.get("status") == "needs_review" and classified.get("failure_stage") == "paypal_human_verification":
            # 可能是 DataDome blocked 页面被泛匹配为 human_verification → 检查并刷新
            page = getattr(api, "page", None)
            if page and _is_ddc_blocked_page(page):
                ddc_blocked_refresh_count += 1
                if ddc_blocked_refresh_count <= _MAX_DDC_BLOCKED_REFRESHES:
                    logger.info("[paypal_authorize] human_verification is actually a blocked page, refreshing (%d/%d)...",
                               ddc_blocked_refresh_count, _MAX_DDC_BLOCKED_REFRESHES)
                    _emit_progress(on_progress, _progress_event(
                        "paypal_ddc_blocked_retry",
                        f"DataDome 封锁页面被误判为人机验证，正在刷新重试 ({ddc_blocked_refresh_count}/{_MAX_DDC_BLOCKED_REFRESHES})",
                    ))
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    time.sleep(4)
                    continue
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            _capture_screenshot(api, session_id, "paypal-authorize-review", screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified

        if paypal_mode == "create_account":
            state["signup_email_submitted"] = signup_email_submitted
            state["signup_email_submitted_at"] = signup_email_submitted_at
            state["signup_submitted"] = signup_form_submitted
            state["signup_submitted_at"] = signup_submitted_at
            state["submitted_phone_keys"] = submitted_phone_keys
            state["phone_only_retry"] = phone_only_retry
            state["card_retry_count"] = card_retry_count
            state["otp_phone_lock_key"] = otp_phone_lock_key
            ok, error, handled = _run_paypal_signup_flow(
                api,
                signup_profile=active_signup_profile,
                state=state,
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            if bool(state.get("signup_email_submitted")) and not signup_email_submitted:
                signup_email_submitted_at = float(state.get("signup_email_submitted_at") or time.time())
                signup_email_submitted = True
            elif bool(state.get("signup_email_submitted")) and signup_email_submitted:
                # 同步回外层（JS 恢复/reload 可能更新了时间戳）
                state_submitted_at = float(state.get("signup_email_submitted_at") or 0)
                if state_submitted_at > 0:
                    signup_email_submitted_at = state_submitted_at
            elif not bool(state.get("signup_email_submitted")) and signup_email_submitted:
                # Layer 1 的 reload 重置了状态 → 外层也要同步重置
                signup_email_submitted = False
                signup_email_submitted_at = 0.0
            if bool(state.get("signup_submitted")) and not signup_form_submitted:
                signup_submitted_at = float(state.get("signup_submitted_at") or time.time())
                signup_form_submitted = True
            elif bool(state.get("signup_submitted_at")):
                signup_submitted_at = float(state.get("signup_submitted_at") or signup_submitted_at)
            phone_only_retry = bool(state.get("phone_only_retry"))
            card_retry_count = int(state.get("card_retry_count") or card_retry_count)
            otp_phone_lock_key = str(state.get("otp_phone_lock_key") or "")
            if not ok:
                if otp_phone_lock_key:
                    _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                    otp_phone_lock_key = ""
                _capture_screenshot(api, session_id, "paypal-signup-failed", screenshot_paths)
                return _build_result(
                    "failed",
                    failure_stage="paypal_signup",
                    message=error,
                    screenshot_paths=screenshot_paths,
                )
            if handled:
                continue
            # 诊断日志：signup_flow 返回 handled=False，检查页面状态
            if signup_email_submitted:
                logger.info(
                    "[paypal_authorize] signup_flow returned handled=False, state: "
                    "email_locator=%s needs_login=%s registration_ready=%s "
                    "registration_text_hint=%s needs_otp=%s approve_ready=%s "
                    "js_count=%s reload_cycles=%s elapsed=%.0f url=%s",
                    bool(state.get("email_locator")),
                    bool(state.get("needs_login")),
                    bool(state.get("registration_ready")),
                    bool(state.get("registration_text_hint")),
                    bool(state.get("needs_otp")),
                    bool(state.get("approve_ready")),
                    state.get("_email_stuck_recover_count", 0),
                    state.get("_email_reload_cycle_count", 0),
                    time.time() - signup_email_submitted_at if signup_email_submitted_at > 0 else 0,
                    _safe_url_summary(getattr(api.page, "url", "")),
                )
            # ── Layer 2: SPA 卡住恢复（与 Layer 1 共享计数器） ──
            # 当 signup_flow 返回 handled=False 且邮箱已提交但无任何表单元素可见时，
            # 说明 SPA 内部状态死锁。使用与 Layer 1 相同的策略：
            #   1 次 JS 快速尝试 → reload + 完整重置 → 最多 3 次 reload 周期
            if (
                signup_email_submitted
                and not state.get("needs_login")
                and not state.get("email_locator")
                and not state.get("registration_ready")
                and not state.get("registration_text_hint")
                and not state.get("needs_otp")
                and not state.get("approve_ready")
            ):
                # 超时退出（使用首次提交时间）
                first_submitted_at = float(state.get("_email_first_submitted_at") or signup_email_submitted_at)
                if first_submitted_at > 0 and time.time() - first_submitted_at > PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS:
                    _capture_screenshot(api, session_id, "paypal-signup-email-timeout", screenshot_paths)
                    return _build_result(
                        "failed",
                        failure_stage="paypal_signup",
                        message="等待 PayPal 注册表单加载超时",
                        screenshot_paths=screenshot_paths,
                    )
                stuck_elapsed = time.time() - signup_email_submitted_at if signup_email_submitted_at > 0 else 0
                _MAX_JS_BEFORE_RELOAD = 1
                _MAX_RELOAD_CYCLES = 3
                js_count = int(state.get("_email_stuck_recover_count") or 0)
                reload_cycles = int(state.get("_email_reload_cycle_count") or 0)

                if (
                    stuck_elapsed > PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS
                    and (js_count <= _MAX_JS_BEFORE_RELOAD or reload_cycles < _MAX_RELOAD_CYCLES)
                ):
                    if js_count < _MAX_JS_BEFORE_RELOAD:
                        # ── JS 快速尝试 ──
                        state["_email_stuck_recover_count"] = js_count + 1
                        recover_email = str(active_signup_profile.get("email") or "").strip()
                        logger.info(
                            "[paypal_authorize] page stuck (%.0fs, %.0fs total), JS recover %d...",
                            stuck_elapsed, time.time() - first_submitted_at, js_count + 1,
                        )
                        _emit_progress(on_progress, _progress_event(
                            "paypal_signup_email_reload",
                            f"邮箱提交后页面卡住（无表单元素），JS 恢复 ({js_count + 1}/{_MAX_JS_BEFORE_RELOAD})",
                        ))
                        recover_result = _js_recover_paypal_email_spinner(api, recover_email)
                        logger.info("[paypal_authorize] JS recover result: %s", recover_result)
                        if not recover_result.get("recovered"):
                            signup_email_submitted = False
                            signup_email_submitted_at = 0.0
                        time.sleep(2.0)
                        continue

                    if reload_cycles < _MAX_RELOAD_CYCLES:
                        # ── Reload + 完整状态重置 ──
                        reload_cycles += 1
                        state["_email_reload_cycle_count"] = reload_cycles
                        state["_email_stuck_recover_count"] = 0
                        state["_email_first_submitted_at"] = 0
                        state["signup_email_submitted"] = False
                        state["signup_email_submitted_at"] = 0
                        state["_fill_retry_count"] = 0
                        signup_email_submitted = False
                        signup_email_submitted_at = 0.0
                        logger.info(
                            "[paypal_authorize] SPA deadlocked, reload cycle %d/%d (%.0fs total)...",
                            reload_cycles, _MAX_RELOAD_CYCLES,
                            time.time() - first_submitted_at,
                        )
                        _emit_progress(on_progress, _progress_event(
                            "paypal_signup_email_reload",
                            f"SPA 死锁，正在刷新页面重试 (第 {reload_cycles}/{_MAX_RELOAD_CYCLES} 轮)",
                        ))
                        try:
                            api.page.reload(wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass
                        time.sleep(3.0)
                        continue
            if state.get("needs_login") or state.get("email_locator") or state.get("registration_ready"):
                time.sleep(1.5)
                continue

        if (
            state.get("has_passkey_prompt")
            and not state.get("needs_otp")
            and _dismiss_paypal_prompts(api, on_progress=on_progress)
        ):
            time.sleep(1.2)
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
            if otp_phone_lock_key:
                _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
                otp_phone_lock_key = ""
            return _wait_for_paypal_subscription_return(
                api,
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                timeout_seconds=PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
            )

        time.sleep(1.0)

    if otp_phone_lock_key:
        _release_paypal_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
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
    checkout_url: str = "",
    proxy_url: str | None = None,
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
    last_stripe_poll_at = 0.0
    autofilled_urls: set[str] = set()
    stripe_state_http = _new_http_session(proxy_url, require_curl_cffi=False)

    def _autofill_key(url: str) -> str:
        parts = urlsplit(str(url or ""))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    last_ddc_check_at_result = 0.0
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
        if _is_paypal_host(current_url):
            _ensure_paypal_hosted_captcha_bypass(api)
            # DataDome DDC 检测：等待结果阶段也可能弹出
            page = getattr(api, "page", None)
            if page:
                # 先检测 blocked 页面
                if _is_ddc_blocked_page(page):
                    logger.info("[paypal_result] blocked page detected, refreshing...")
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    time.sleep(4)
                    continue

                slider_visible = _ddc_slider_visible(page)
                ddc_iframe_present = (
                    (not slider_visible)
                    and (time.time() - last_ddc_check_at_result > 15)
                    and _has_ddc_iframe(page)
                )
                if slider_visible or ddc_iframe_present:
                    last_ddc_check_at_result = time.time()
                    _wait_ddc_pass(page, timeout_seconds=50, on_progress=on_progress)
        should_autofill_checkout = (
            bool(autofill_payload)
            and _is_checkout_host(current_url)
            and _autofill_allowed(current_url)
        )
        autofill_key = _autofill_key(current_url)
        if should_autofill_checkout and autofill_key not in autofilled_urls:
            autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)
            autofilled_urls.add(autofill_key)
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

        if checkout_url and now - last_stripe_poll_at >= PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS:
            last_stripe_poll_at = now
            stripe_classified = _fetch_paypal_stripe_payment_page_state(checkout_url, http=stripe_state_http)
            if stripe_classified:
                _emit_progress(
                    on_progress,
                    _progress_event(
                        "paypal_result_confirmed_by_stripe",
                        stripe_classified.get("message") or "Stripe checkout 状态已确认",
                        checkout_url=checkout_url,
                        url=current_url,
                    ),
                )
                _capture_screenshot(api, session_id, stripe_classified["status"], screenshot_paths)
                stripe_classified["screenshot_paths"] = screenshot_paths
                return stripe_classified

        time.sleep(3)

    _capture_screenshot(api, session_id, "paypal-timeout", screenshot_paths)
    return _build_result(
        "needs_review",
        failure_stage="post_submit",
        message="等待 PayPal 支付结果超时，需要人工确认最终状态",
        screenshot_paths=screenshot_paths,
    )


def _bounded_timeout_seconds(value: int | None, *, minimum: int, maximum: int) -> int:
    requested = int(value or 0)
    if requested <= 0:
        return minimum
    return max(minimum, min(requested, maximum))


def _paypal_authorize_timeout_seconds(timeout_seconds: int | None) -> int:
    return _bounded_timeout_seconds(
        timeout_seconds,
        minimum=PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS,
        maximum=PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS,
    )


def _paypal_result_timeout_seconds(timeout_seconds: int | None) -> int:
    return _bounded_timeout_seconds(
        timeout_seconds,
        minimum=PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS,
        maximum=PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS,
    )


def _run_paypal_auto_flow(
    api: ChatGPTTeamAPI,
    *,
    email: str,
    checkout_url: str = "",
    proxy_url: str | None = None,
    paypal_mode: str,
    paypal_credentials: dict[str, str],
    signup_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None = None,
    billing_payload: dict[str, str] | None = None,
    paypal_country: str = "US",
    paypal_lang: str = "en",
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
    autofill_enabled: bool = False,
    autofill_payload: dict | None = None,
):
    current_url = getattr(api.page, "url", "")
    billing_payload = dict(billing_payload or _resolve_checkout_billing_payload(autofill_payload, auto_generate=bool(autofill_enabled)))
    paypal_country = _normalize_paypal_country(paypal_country or str(billing_payload.get("country") or "US"))
    paypal_lang = _normalize_paypal_lang(paypal_lang, paypal_country)
    progress = _progress_adapter(on_progress)
    authorize_timeout_seconds = _paypal_authorize_timeout_seconds(timeout_seconds)
    result_timeout_seconds = _paypal_result_timeout_seconds(timeout_seconds)

    if _is_checkout_host(current_url):
        nonzero_hint = _browser_checkout_nonzero_amount_hint(api)
        if nonzero_hint:
            _capture_screenshot(api, session_id, "paypal-browser-nonzero-amount-blocked", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="browser_charge_guard",
                message=f"浏览器 checkout 页面今日应付金额非 0 ({nonzero_hint})，已跳过当前账号",
                screenshot_paths=screenshot_paths,
            )
        if not _select_paypal_option(api, on_progress=on_progress):
            _capture_screenshot(api, session_id, "paypal-option-not-found", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="select_paypal",
                message="未找到 PayPal 支付方式按钮",
                screenshot_paths=screenshot_paths,
            )
        if _autofill_allowed(getattr(api.page, "url", "")):
            if not _has_complete_billing_payload(billing_payload):
                _capture_screenshot(api, session_id, "paypal-billing-address-incomplete", screenshot_paths)
                return _build_result(
                    "failed",
                    failure_stage="fill_billing_info",
                    message="账单地址缺少必要字段",
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
            _accept_checkout_terms_on_page(api, progress=progress)
            _emit_progress(
                on_progress,
                _progress_event("paypal_billing_fill_done", url=getattr(api.page, "url", "")),
            )
        else:
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
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        credentials=paypal_credentials,
        signup_profile=signup_profile,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=authorize_timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        phone_accounts=phone_accounts,
    )
    if authorize_result:
        return authorize_result

    return _wait_for_paypal_result(
        api,
        checkout_url=checkout_url or current_url,
        proxy_url=proxy_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=result_timeout_seconds,
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
    phone_accounts: list[dict] | None = None,
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
    paypal_browser: str = "chromium",
    paypal_fallback_browser: str = "",
    paypal_country: str = "US",
    paypal_lang: str = "en",
    roxybrowser_workspace_id: str = "",
    roxybrowser_profile_id: str = "",
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    auto_mode = not bool(manual_confirm)
    paypal_mode = _normalize_paypal_mode(paypal_mode)
    paypal_browser = str(paypal_browser or "chromium").strip().lower()
    paypal_fallback_browser = str(paypal_fallback_browser or "").strip().lower()
    paypal_country = _normalize_paypal_country(paypal_country)
    paypal_lang = _normalize_paypal_lang(paypal_lang, paypal_country)
    protocol_mode = paypal_browser in {"protocol", "http", "no_card", "no-card", "pure_protocol"}
    use_camoufox = paypal_browser in {"camoufox", "firefox"}
    use_roxybrowser = paypal_browser in {"roxybrowser", "roxy-browser", "roxy"}
    fallback_use_roxybrowser = paypal_fallback_browser in {"roxybrowser", "roxy-browser", "roxy"}
    fallback_use_camoufox = paypal_fallback_browser in {"", "protocol", "http", "no_card", "no-card", "pure_protocol", "camoufox", "firefox"}
    launch_proxy_url = str(proxy_url or "").strip() or None
    launch_proxy_bypass = str(proxy_bypass or "").strip() or None
    roxybrowser_workspace_id = str(roxybrowser_workspace_id or "").strip()
    roxybrowser_profile_id = str(roxybrowser_profile_id or "").strip()

    def _preserve_roxybrowser_on_failure(result: dict):
        if fallback_use_roxybrowser and str(result.get("status") or "") != "success":
            setattr(api, "_preserve_roxybrowser_on_stop", True)
            setattr(api, "_preserve_roxybrowser_on_stop_seconds", PAYPAL_ROXYBROWSER_FAILURE_KEEPALIVE_SECONDS)
        return result

    def _launch_browser_for_checkout(current_proxy_url: str | None, current_proxy_bypass: str | None) -> None:
        browser_locale = f"{paypal_lang}-{paypal_country}"
        browser_accept_language = f"{paypal_lang}-{paypal_country},{paypal_lang};q=0.9,en;q=0.8"
        api._launch_browser(
            proxy_url=current_proxy_url,
            proxy_bypass=current_proxy_bypass,
            background=False,
            locale=browser_locale,
            accept_language=browser_accept_language,
            randomize_fingerprint=False,
            use_camoufox=use_camoufox,
            use_roxybrowser=use_roxybrowser,
            roxybrowser_workspace_id=roxybrowser_workspace_id,
            roxybrowser_profile_id=roxybrowser_profile_id,
            on_progress=on_progress,
        )

    try:
        if protocol_mode:
            billing_payload = _resolve_checkout_billing_payload(autofill_payload, auto_generate=bool(autofill_enabled))
            protocol_result = _run_paypal_protocol_flow(
                email=str(email or "").strip(),
                checkout_url=checkout_url,
                proxy_url=launch_proxy_url,
                paypal_mode=paypal_mode,
                paypal_country=paypal_country,
                paypal_lang=paypal_lang,
                signup_profile=_build_paypal_signup_profile(
                    paypal_email=paypal_email,
                    paypal_password=paypal_password,
                    billing_payload=billing_payload,
                    sms_url=sms_url,
                    otp_channel=otp_channel,
                    phone_accounts=phone_accounts,
                    paypal_card_number=paypal_card_number,
                    paypal_card_expiry=paypal_card_expiry,
                    paypal_card_cvv=paypal_card_cvv,
                ),
                phone_accounts=phone_accounts,
                billing_payload=billing_payload,
                timeout_seconds=timeout_seconds,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
            )
            if not _paypal_protocol_needs_browser_fallback(protocol_result):
                return protocol_result

            # ── 协议模式被风控拦截，降级到 Camoufox 浏览器 ──
            fallback_approve_url = str(protocol_result.get("paypal_approve_url") or "")
            fallback_ba_token = str(protocol_result.get("ba_token") or "")
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_protocol_browser_fallback",
                    "协议模式被 PayPal 风控拦截，正在降级到浏览器模式",
                    paypal_approve_url=_safe_url_summary(fallback_approve_url),
                    ba_token=fallback_ba_token,
                ),
            )
            if not fallback_approve_url:
                return protocol_result

            api._launch_browser(
                proxy_url=launch_proxy_url,
                proxy_bypass=launch_proxy_bypass,
                background=False,
                locale=f"{paypal_lang}-{paypal_country}",
                accept_language=f"{paypal_lang}-{paypal_country},{paypal_lang};q=0.9,en;q=0.8",
                use_camoufox=fallback_use_camoufox,
                use_roxybrowser=fallback_use_roxybrowser,
                roxybrowser_workspace_id=roxybrowser_workspace_id,
                roxybrowser_profile_id=roxybrowser_profile_id,
                on_progress=on_progress,
            )
            page = api.page
            _emit_progress(on_progress, _progress_event("paypal_browser_fallback_navigate"))
            page.goto(fallback_approve_url, wait_until="domcontentloaded", timeout=60000)
            # 等待 DataDome 自然通过或解滑块
            _emit_progress(on_progress, _progress_event("paypal_browser_fallback_ddc_wait"))
            ddc_passed = _wait_ddc_pass(page, timeout_seconds=50, on_progress=on_progress)
            if not ddc_passed:
                return _preserve_roxybrowser_on_failure(
                    _build_result(
                        "failed",
                        failure_stage="paypal_datadome_blocked",
                        message="浏览器降级后 DataDome 滑块/风控仍未通过",
                    )
                )

            _ensure_paypal_hosted_captcha_bypass(api)
            authorize_result = _run_paypal_authorize_flow(
                api,
                paypal_mode=paypal_mode,
                paypal_country=paypal_country,
                paypal_lang=paypal_lang,
                credentials=_normalize_paypal_credentials(paypal_email, paypal_password),
                signup_profile=_build_paypal_signup_profile(
                    paypal_email=paypal_email,
                    paypal_password=paypal_password,
                    billing_payload=billing_payload,
                    sms_url=sms_url,
                    otp_channel=otp_channel,
                    phone_accounts=phone_accounts,
                    paypal_card_number=paypal_card_number,
                    paypal_card_expiry=paypal_card_expiry,
                    paypal_card_cvv=paypal_card_cvv,
                ),
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                timeout_seconds=_paypal_authorize_timeout_seconds(timeout_seconds),
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                phone_accounts=phone_accounts,
            )
            if authorize_result:
                return _preserve_roxybrowser_on_failure(authorize_result)
            return _preserve_roxybrowser_on_failure(
                _wait_for_paypal_result(
                    api,
                    checkout_url=checkout_url,
                    session_id=session_id,
                    screenshot_paths=screenshot_paths,
                    timeout_seconds=_paypal_result_timeout_seconds(timeout_seconds),
                    is_cancelled=is_cancelled,
                    on_progress=on_progress,
                    autofill_enabled=False,
                    autofill_payload=None,
                )
            )

        _launch_browser_for_checkout(launch_proxy_url, launch_proxy_bypass)

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
        if (
            prepare_result
            and prepare_result.get("failure_stage") == "open_checkout"
            and launch_proxy_url
        ):
            retry_message = "代理打开 checkout 失败，已停止当前账号；不会切换直连重试"
            if _is_tunnel_connection_error(prepare_result.get("message")):
                retry_message = "代理隧道打开 checkout 失败，已停止当前账号；不会切换直连重试"
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_proxy_open_checkout_failed",
                    retry_message,
                    level="warn",
                ),
            )
            logger.info(
                "[paypal_bind_executor] checkout open failed with proxy, not retrying direct: proxy=%s",
                _safe_url_summary(launch_proxy_url),
            )
            return _build_result(
                "failed",
                failure_stage="open_checkout_proxy",
                message=f"{retry_message}: {prepare_result.get('message') or '未知错误'}",
                screenshot_paths=screenshot_paths,
            )
        if prepare_result:
            return prepare_result

        if auto_mode:
            billing_payload = _resolve_checkout_billing_payload(autofill_payload, auto_generate=bool(autofill_enabled))
            return _run_paypal_auto_flow(
                api,
                email=str(email or "").strip(),
                checkout_url=checkout_url,
                proxy_url=launch_proxy_url,
                paypal_mode=paypal_mode,
                paypal_country=paypal_country,
                paypal_lang=paypal_lang,
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
                phone_accounts=phone_accounts,
                billing_payload=billing_payload,
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                timeout_seconds=timeout_seconds,
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                autofill_enabled=autofill_enabled,
                autofill_payload=autofill_payload,
            )

        if autofill_payload:
            autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)

        return _wait_for_paypal_result(
            api,
            checkout_url=checkout_url,
            proxy_url=launch_proxy_url,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=_paypal_result_timeout_seconds(timeout_seconds),
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
