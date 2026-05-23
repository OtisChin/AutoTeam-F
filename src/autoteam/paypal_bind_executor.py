"""PayPal 自动/人工绑定执行器。"""

from __future__ import annotations

import logging
import json
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
    DEFAULT_STRIPE_PK,
    GoPayOTPCancelled,
    STRIPE_API,
    STRIPE_VERSION_FULL,
    _accept_checkout_terms_on_page,
    _browser_checkout_nonzero_amount_hint,
    _dismiss_address_autocomplete,
    _extract_checkout_session_id,
    _extract_checkout_error,
    _inject_chatgpt_browser_cookies,
    _new_http_session,
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
PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS = 240
PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS = 60
PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS = 420
PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS = 180
PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS = 5.0


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
PAYPAL_PHONE_REJECTED_SELECTORS = [
    '[role="dialog"]:has-text("Try a different phone number")',
    '[aria-modal="true"]:has-text("Try a different phone number")',
    'text="Try a different phone number"',
    'text="We’re unable to complete your request"',
    "text=\"We're unable to complete your request\"",
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
    '#btnNext',
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
    'input[id*="phone" i]',
    'input[name*="phone" i]',
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
    'input[placeholder*="state" i]',
    'input[aria-label*="state" i]',
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
    'button:has-text("Try another way")',
    'button:has-text("Use password instead")',
    'button:has-text("以后再说")',
    'button:has-text("暂不")',
    'button:has-text("改用密码")',
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
    "paypal_authorize": "已进入 PayPal 页面，开始自动登录/授权",
    "paypal_login_email": "正在填写 PayPal 邮箱",
    "paypal_login_password": "正在填写 PayPal 密码",
    "paypal_create_account": "正在切换到 PayPal 注册流程",
    "paypal_signup_email": "正在填写 PayPal 注册邮箱",
    "paypal_wait_signup_form": "正在等待 PayPal 注册表单加载",
    "paypal_fill_signup": "正在填写 PayPal 注册表单",
    "paypal_submit_signup": "正在提交 PayPal 注册信息",
    "paypal_wait_signup_otp": "正在等待 PayPal 短信验证码",
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
}


def classify_paypal_checkout_state(url: str, body_text: str):
    normalized_url = str(url or "").strip().lower()
    normalized_body = str(body_text or "").strip().lower()
    haystack = f"{normalized_url}\n{normalized_body}"
    parsed_url = urlsplit(normalized_url)
    query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    fragment_params = dict(parse_qsl(parsed_url.fragment, keep_blank_values=True))
    redirect_status = str(query_params.get("redirect_status") or fragment_params.get("redirect_status") or "").lower()

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

    if CANCEL_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in CANCEL_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付已取消",
        }

    if FAILURE_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in FAILURE_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal/支付失败提示",
        }

    if (
        redirect_status in {"succeeded", "success", "complete", "completed"}
        or "setup_intent=" in normalized_url and "redirect_pm_type=paypal" in normalized_url
        or SUCCESS_URL_RE.search(parsed_url.path)
        or any(hint in haystack for hint in SUCCESS_HINTS)
    ):
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
    generated_raw = _fetch_paypal_random_billing_profile()
    generated = _public_paypal_billing_info(generated_raw)
    merged = {
        "name": str(generated.get("name") or DEFAULT_PAYPAL_NAME).strip() or DEFAULT_PAYPAL_NAME,
        "email": str(requested.get("email") or "").strip(),
        "phone": str(requested.get("phone") or generated.get("phone_number") or "").strip(),
        "country": "US",
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


def _normalize_us_state_value(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    if not normalized:
        return ""
    upper = normalized.upper()
    if upper in US_STATE_CODE_TO_NAME:
        return upper
    return US_STATE_NAME_TO_CODE.get(normalized, upper)


def _state_value_matches(expected: str, actual: str) -> bool:
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

    for setter in (_set_locator_value, _type_locator_value, _dispatch_locator_value):
        if setter(locator, value):
            time.sleep(0.2)
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
      const rejected = (text) => /try a different phone number|unable to complete your request/i.test(text || '');
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
    script = r"""(profile) => {
      const values = profile || {};
      const filled = [];
      const missing = [];
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const digits = (value) => String(value || '').replace(/\D+/g, '');
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
      const controls = Array.from(document.querySelectorAll('input, select, textarea'))
        .filter((el) => isVisible(el) && !el.disabled && !el.readOnly);
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
        const candidates = controls.map((el) => ({ el, text: textAround(el), tag: String(el.tagName || '').toLowerCase(), type: String(el.type || '').toLowerCase() }));
        const by = (predicate) => candidates.find(predicate)?.el || null;
        if (field === 'country') return by((c) => c.tag === 'select' && /country|region/.test(c.text));
        if (field === 'email') return by((c) => c.type === 'email' || /\bemail\b/.test(c.text));
        if (field === 'phone') return by((c) => c.tag !== 'select' && /phone number|mobile number|telephone|phone/.test(c.text) && !/phone type/.test(c.text));
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
        return null;
      };
      const valueMatches = (field, actual, expected) => {
        if (!expected) return true;
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
      const required = ['email', 'phone', 'card_number', 'card_expiry', 'card_cvv', 'first_name', 'last_name', 'address1', 'city', 'state', 'zip', 'password'];
      const stillMissing = [];
      for (const field of required) {
        const expected = values[field];
        const control = findControl(field);
        const actual = control ? (control.value || control.textContent || '') : '';
        if (!control || !valueMatches(field, actual, expected)) stillMissing.push(field);
      }
      return { filled, missing, stillMissing };
    }"""
    try:
        result = api.page.evaluate(script, payload)
        return result if isinstance(result, dict) else {"filled": [], "missing": [], "stillMissing": []}
    except Exception as exc:
        return {"filled": [], "missing": ["dom"], "stillMissing": ["dom"], "error": str(exc)}


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
        if _field_value_matches(expected, actual, field=key):
            continue
        if not _set_locator_value(locator, expected):
            return False, f"{label} 自动补全后被改写，且重写失败"
        if key == "address1":
            _dismiss_address_autocomplete(api, locator)
        time.sleep(0.3)
        actual = _read_locator_value(locator)
        if not _field_value_matches(expected, actual, field=key):
            return False, f"{label} 自动补全后校验失败: 期望={expected!r}, 实际={actual!r}"
    dom_result = _fill_paypal_signup_visible_form(api, signup_profile)
    still_missing = [str(item) for item in dom_result.get("stillMissing") or [] if str(item)]
    if still_missing:
        logger.info(
            "[paypal_bind_executor] PayPal signup DOM validation could not confirm fields: %s",
            ", ".join(still_missing),
        )
    return True, ""


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
    if not _click_first(api, PAYPAL_SIGNUP_EMAIL_SUBMIT_SELECTORS, timeout_ms=2500):
        try:
            email_locator.press("Enter", timeout=1200)
        except Exception:
            return False, "未找到 PayPal 注册邮箱提交按钮"
    time.sleep(2.0)
    return True, ""


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
        timeout_seconds=max(60, timeout_seconds),
        initial_delay_seconds=8,
        resend_after_seconds=60,
        max_resend_attempts=2,
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
        if state.get("card_rejected"):
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
            if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
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
                timeout_seconds=180,
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
        time.sleep(2.0)
        return True, "", True

    if phone_only_retry and (state.get("registration_ready") or state.get("registration_text_hint")):
        ok, error = _replace_paypal_signup_phone(api, signup_profile=signup_profile, on_progress=on_progress)
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
        if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
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

    if (
        state.get("email_locator")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
    ):
        if signup_email_submitted:
            submitted_at = float(state.get("signup_email_submitted_at") or 0)
            if submitted_at > 0 and time.time() - submitted_at > PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS:
                return False, "等待 PayPal 注册表单加载超时", False
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
        ok, error = _fill_paypal_signup_form(api, signup_profile=signup_profile, on_progress=on_progress)
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
        if not _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=2500):
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
    is_cancelled=None,
    on_progress=None,
    phone_accounts: list[dict] | None = None,
):
    deadline = time.time() + max(20, timeout_seconds)
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
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        active_phone_key = _normalize_paypal_phone(str(active_signup_profile.get("phone") or ""))
        active_phone_submitted = bool(active_phone_key and active_phone_key in submitted_phone_keys)
        if not signup_form_submitted and not active_phone_submitted:
            _force_paypal_us_locale(api)
        current_url = getattr(api.page, "url", "")
        if current_url and not _is_paypal_host(current_url):
            _emit_progress(on_progress, _progress_event("paypal_wait_result", url=current_url))
            return None
        _ensure_paypal_hosted_captcha_bypass(api)

        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="post_submit", message="任务已取消", screenshot_paths=screenshot_paths)

        state = _inspect_paypal_page(api)
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

        if paypal_mode == "create_account":
            state["signup_email_submitted"] = signup_email_submitted
            state["signup_email_submitted_at"] = signup_email_submitted_at
            state["signup_submitted"] = signup_form_submitted
            state["signup_submitted_at"] = signup_submitted_at
            state["submitted_phone_keys"] = submitted_phone_keys
            state["phone_only_retry"] = phone_only_retry
            state["card_retry_count"] = card_retry_count
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
            if bool(state.get("signup_submitted")) and not signup_form_submitted:
                signup_submitted_at = float(state.get("signup_submitted_at") or time.time())
                signup_form_submitted = True
            elif bool(state.get("signup_submitted_at")):
                signup_submitted_at = float(state.get("signup_submitted_at") or signup_submitted_at)
            phone_only_retry = bool(state.get("phone_only_retry"))
            card_retry_count = int(state.get("card_retry_count") or card_retry_count)
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
    progress = _progress_adapter(on_progress)
    authorize_timeout_seconds = max(PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS, int(timeout_seconds or 0))
    result_timeout_seconds = max(PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS, int(timeout_seconds or 0))

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
    paypal_browser: str = "camoufox",
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    auto_mode = not bool(manual_confirm)
    paypal_mode = _normalize_paypal_mode(paypal_mode)
    paypal_browser = str(paypal_browser or "camoufox").strip().lower()
    use_camoufox = paypal_browser not in {"chromium", "chrome", "playwright"}
    launch_proxy_url = str(proxy_url or "").strip() or None
    launch_proxy_bypass = str(proxy_bypass or "").strip() or None

    def _launch_browser_for_checkout(current_proxy_url: str | None, current_proxy_bypass: str | None) -> None:
        api._launch_browser(
            proxy_url=current_proxy_url,
            proxy_bypass=current_proxy_bypass,
            background=False,
            locale="en-US",
            accept_language="en-US,en;q=0.9",
            use_camoufox=use_camoufox,
        )

    try:
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
