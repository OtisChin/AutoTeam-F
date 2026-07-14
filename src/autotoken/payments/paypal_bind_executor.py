"""PayPal 自动/人工绑定执行器。"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from autotoken.core.redaction import (
    compact_log_text as _compact_log_text,
)
from autotoken.core.redaction import (
    safe_error_summary as _safe_error_summary,
)
from autotoken.core.redaction import (
    safe_proxy_summary as _safe_proxy_summary,
)
from autotoken.core.redaction import (
    safe_url_summary as _safe_url_summary,
)
from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
from autotoken.payments.bind_executor import _build_result, _capture_screenshot
from autotoken.payments.paypal_protocol_signup import run_paypal_no_card_protocol_signup
from autotoken.services import chatgpt_session as chatgpt_session_service
from autotoken.services import payment_checkout_browser as payment_checkout_browser_service
from autotoken.services import payment_checkout_state as payment_checkout_state_service
from autotoken.services import payment_errors as payment_errors_service
from autotoken.services import payment_form_fields as payment_form_fields_service
from autotoken.services import payment_http as payment_http_service
from autotoken.services import payment_stripe as payment_stripe_service
from autotoken.services import paypal_billing_agreement as paypal_billing_agreement_service
from autotoken.services import paypal_mockaddress as paypal_mockaddress_service
from autotoken.services import paypal_preflight as paypal_preflight_service
from autotoken.services import paypal_proxy as paypal_proxy_service
from autotoken.services import paypal_task_payloads as paypal_task_payloads_service
from autotoken.services import proxy_runtime as proxy_runtime_service
from autotoken.services import sms_otp as sms_otp_service
from autotoken.storage.auth_session_store import load_auth_session

logger = logging.getLogger(__name__)
DEFAULT_PAYPAL_NAME = "James Smith"
PAYPAL_ADDRESS_GENERATOR_URL = "https://www.meiguodizhi.com/api/v1/dz"
PAYPAL_ADDRESS_GENERATOR_REFERER = "https://www.meiguodizhi.com/"
MOCKADDRESS_JP_DATA_URL = "https://mockaddress.com/data/jpData.json"
MOCKADDRESS_JP_REAL_AREAS_URL = "https://mockaddress.com/data/jpRealAreas.json"
MOCKADDRESS_JP_NAMES_DATA_URL = "https://mockaddress.com/data/jpNamesData.json"
MOCKADDRESS_NAMES_DATA_URL = "https://mockaddress.com/data/namesData.json"
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
_MOCKADDRESS_JP_CACHE: dict[str, Any] = {}
DEFAULT_STRIPE_PK = payment_stripe_service.DEFAULT_STRIPE_PK
DEFAULT_STRIPE_RUNTIME_VERSION = payment_stripe_service.DEFAULT_STRIPE_RUNTIME_VERSION
STRIPE_API = payment_stripe_service.STRIPE_API
STRIPE_VERSION_FULL = payment_stripe_service.STRIPE_VERSION_FULL
GoPayFlowError = payment_errors_service.PaymentFlowError
GoPayOTPCancelled = payment_errors_service.PaymentOTPCancelled


class _PayPalOpllRequiresApproval(RuntimeError):
    pass


def _extract_checkout_error(api: ChatGPTTeamAPI) -> str:
    return payment_checkout_state_service.extract_checkout_error(api, body_excerpt=_body_excerpt)


def _browser_checkout_nonzero_amount_hint(api: ChatGPTTeamAPI) -> str:
    return payment_checkout_state_service.browser_checkout_nonzero_amount_hint(api, body_excerpt=_body_excerpt)


def _dismiss_address_autocomplete(api: ChatGPTTeamAPI, address1_locator=None):
    return payment_checkout_browser_service.dismiss_address_autocomplete(
        api,
        address1_locator,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
    )


def _suppress_address_autocomplete_ui(api: ChatGPTTeamAPI):
    return payment_checkout_browser_service.suppress_address_autocomplete_ui(api)


def _accept_checkout_terms_on_page(api: ChatGPTTeamAPI, progress=None) -> int:
    return payment_checkout_browser_service.accept_checkout_terms_on_page(
        api,
        progress=progress,
        frames=_iter_page_frames,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
    )


def _is_checkout_page(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.is_checkout_page(api, body_excerpt=_body_excerpt)


def _goto_with_retry(
    page, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 60000, attempts: int = 3
) -> bool:
    return payment_checkout_browser_service.goto_with_retry(
        page,
        url,
        wait_until=wait_until,
        timeout=timeout,
        attempts=attempts,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
        safe_url_summary=_safe_url_summary,
        safe_error_summary=_safe_error_summary,
    )


def _select_chatgpt_account_if_needed(api: ChatGPTTeamAPI, email: str = "") -> bool:
    return payment_checkout_browser_service.select_chatgpt_account_if_needed(
        api,
        email=email,
        body_excerpt=_body_excerpt,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
        safe_error_summary=_safe_error_summary,
        compact_log_text=_compact_log_text,
    )


def _log_browser_auth_session_diag(api: ChatGPTTeamAPI, *, label: str):
    return payment_checkout_browser_service.log_browser_auth_session_diag(
        api,
        label=label,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
        safe_error_summary=_safe_error_summary,
        compact_log_text=_compact_log_text,
    )


def _open_checkout_in_page(api: ChatGPTTeamAPI, checkout_url: str, email: str = "") -> bool:
    return payment_checkout_browser_service.open_checkout_in_page(
        api,
        checkout_url,
        email=email,
        goto=_goto_with_retry,
        is_checkout=_is_checkout_page,
        body_excerpt=_body_excerpt,
        extract_checkout_session_id=_extract_checkout_session_id,
        select_account=lambda checkout_api, target_email: _select_chatgpt_account_if_needed(
            checkout_api,
            email=target_email,
        ),
        log_auth_session_diag=lambda checkout_api, label: _log_browser_auth_session_diag(checkout_api, label=label),
        logger=logger,
        log_prefix="[paypal_bind_executor]",
        safe_error_summary=_safe_error_summary,
        safe_url_summary=_safe_url_summary,
        compact_log_text=_compact_log_text,
    )


def _new_http_session(
    proxy_url: str | None = None,
    *,
    require_curl_cffi: bool = False,
    force_requests: bool = False,
) -> Any:
    try:
        return payment_http_service.new_http_session(
            proxy_url,
            require_curl_cffi=require_curl_cffi,
            force_requests=force_requests,
        )
    except payment_http_service.PaymentHttpError as exc:
        raise GoPayFlowError(str(exc), stage=getattr(exc, "stage", "chatgpt_http_session")) from exc


class _TlsClientHttpSessionAdapter:
    def __init__(self, session: Any):
        self._session = session
        self.headers = getattr(session, "headers", {})
        self.cookies = getattr(session, "cookies", None)

    @staticmethod
    def _request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        converted = dict(kwargs)
        timeout = converted.pop("timeout", None)
        if timeout is not None and "timeout_seconds" not in converted:
            converted["timeout_seconds"] = int(timeout)
        return converted

    def get(self, url: str, **kwargs: Any):
        return self._session.get(url, **self._request_kwargs(kwargs))

    def post(self, url: str, **kwargs: Any):
        return self._session.post(url, **self._request_kwargs(kwargs))


def _new_paypal_protocol_http_session(proxy_url: str | None = None) -> Any:
    try:
        import tls_client  # type: ignore

        session = tls_client.Session(
            client_identifier=str(os.environ.get("PAYPAL_PROTOCOL_TLS_CLIENT_ID") or "chrome_146").strip(),
            random_tls_extension_order=False,
        )
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
            }
        )
        normalized_proxy = _paypal_pplink_normalize_proxy_url(proxy_url)
        if normalized_proxy:
            session.proxies = {"http": normalized_proxy, "https": normalized_proxy}
        return _TlsClientHttpSessionAdapter(session)
    except Exception as exc:
        logger.info("[paypal_protocol] tls_client session unavailable, using shared HTTP session: %s", exc)
        return _new_http_session(proxy_url, require_curl_cffi=False)


def _response_json(resp, stage: str) -> dict:
    return payment_http_service.response_json(
        resp,
        stage,
        error_factory=lambda message, error_stage: GoPayFlowError(message, stage=error_stage),
    )


def _load_chatgpt_auth_file_context(email: str) -> dict[str, str]:
    return payment_http_service.load_chatgpt_auth_file_context(email)


def _extract_checkout_session_id(checkout_url: str = "", raw: dict | None = None) -> str:
    return payment_stripe_service.extract_checkout_session_id(checkout_url, raw)


def _stripe_runtime_from_env() -> dict:
    return payment_stripe_service.stripe_runtime_from_env()


def _configure_chatgpt_http_session(http, **kwargs):
    return chatgpt_session_service.configure_chatgpt_http_session(http, **kwargs)


def _inject_chatgpt_browser_cookies(api, **kwargs):
    return chatgpt_session_service.inject_chatgpt_browser_cookies(
        api,
        **kwargs,
        missing_context_error_factory=lambda: GoPayFlowError(
            "浏览器上下文未初始化，无法注入 ChatGPT 登录态",
            stage="chatgpt_approve",
        ),
    )


def _cookie_header_from_http_session(http: Any) -> str:
    cookie = chatgpt_session_service.http_session_cookie_header(http)
    if cookie:
        return cookie
    try:
        return str((getattr(http, "headers", {}) or {}).get("Cookie") or "")
    except Exception:
        return ""


def _chatgpt_checkout_headers(
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    target_path: str = "",
    openai_sentinel_token: str = "",
) -> dict[str, str]:
    return chatgpt_session_service.chatgpt_checkout_headers(
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        cookie_header=cookie_header,
        account_id=account_id,
        device_id=device_id,
        target_path=target_path,
        openai_sentinel_token=openai_sentinel_token,
    )


def _checkout_approval_sentinel_headers(
    cookie_header: str = "",
    user_agent: str = "",
    checkout_url: str = "",
) -> dict[str, str]:
    try:
        from autotoken.payments.gopay_executor import _checkout_approval_sentinel_headers as build_headers

        return build_headers(cookie_header=cookie_header, user_agent=user_agent, checkout_url=checkout_url)
    except Exception as exc:
        logger.info("[paypal_extract] Sentinel approval headers unavailable: %s", exc)
        return {}


def _poll_otp_from_sms_url(
    sms_url: str,
    *,
    timeout_seconds: int,
    initial_delay_seconds: float | None = None,
    resend_after_seconds: float | None = None,
    max_resend_attempts: int | None = None,
    is_cancelled=None,
    progress=None,
):
    return sms_otp_service.poll_otp_from_sms_url(
        sms_url,
        timeout_seconds=timeout_seconds,
        initial_delay_seconds=initial_delay_seconds,
        resend_after_seconds=resend_after_seconds,
        max_resend_attempts=max_resend_attempts,
        is_cancelled=is_cancelled,
        progress=progress,
        cancelled_error_factory=lambda message: GoPayOTPCancelled(message, stage="fetch_otp"),
        otp_label="PayPal OTP",
    )


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
PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS = 300
PAYPAL_SIGNUP_OTP_RESEND_AFTER_SECONDS = 60
PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS = 0
PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS = 120
PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS = 30
PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS = payment_checkout_state_service.PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS
PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS = payment_checkout_state_service.PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS
PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS = payment_checkout_state_service.PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS
PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS = payment_checkout_state_service.PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS
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
    return paypal_proxy_service.is_paypal_tunnel_connection_error(value)


SUCCESS_HINTS = payment_checkout_state_service.PAYPAL_SUCCESS_HINTS
PAYPAL_ACCOUNT_LIMITED_HINTS = payment_checkout_state_service.PAYPAL_ACCOUNT_LIMITED_HINTS
PAYPAL_PHONE_REJECTED_HINTS = payment_checkout_state_service.PAYPAL_PHONE_REJECTED_HINTS
PAYPAL_CARD_REJECTED_HINTS = payment_checkout_state_service.PAYPAL_CARD_REJECTED_HINTS
PAYPAL_CARD_LINKED_HINTS = payment_checkout_state_service.PAYPAL_CARD_LINKED_HINTS
PAYPAL_CARD_CANDIDATE_REJECTED_HINTS = payment_checkout_state_service.PAYPAL_CARD_CANDIDATE_REJECTED_HINTS
PAYPAL_FUNDING_REJECTED_HINTS = payment_checkout_state_service.PAYPAL_FUNDING_REJECTED_HINTS
PAYPAL_DATADOME_BLOCKED_HINTS = payment_checkout_state_service.PAYPAL_DATADOME_BLOCKED_HINTS
PAYPAL_HUMAN_VERIFICATION_HINTS = payment_checkout_state_service.PAYPAL_HUMAN_VERIFICATION_HINTS
PAYPAL_PHONE_REJECTED_SELECTORS = [
    '[role="dialog"]:has-text("Try a different phone number")',
    '[aria-modal="true"]:has-text("Try a different phone number")',
    'text="Try a different phone number"',
    'text="We’re unable to complete your request"',
    'text="We\'re unable to complete your request"',
    'text="別の電話番号をお試しください"',
    'text="リクエストを完了できませんでした"',
]
FAILURE_HINTS = payment_checkout_state_service.PAYPAL_FAILURE_HINTS
PENDING_HINTS = payment_checkout_state_service.PAYPAL_PENDING_HINTS
CANCEL_HINTS = payment_checkout_state_service.PAYPAL_CANCEL_HINTS
REVIEW_HINTS = payment_checkout_state_service.PAYPAL_REVIEW_HINTS
SUCCESS_URL_RE = payment_checkout_state_service.PAYPAL_SUCCESS_URL_RE
FAILURE_URL_RE = payment_checkout_state_service.PAYPAL_FAILURE_URL_RE
CANCEL_URL_RE = payment_checkout_state_service.PAYPAL_CANCEL_URL_RE


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
        "#billingAddressLine1",
        'input[name*="addressLine1" i]',
        'input[id*="addressLine1" i]',
        'input[name*="address" i]',
        'input[id*="address" i]',
    ],
    "address2": [
        'input[autocomplete="billing address-line2"]',
        'input[autocomplete="address-line2"]',
        "#billingAddressLine2",
        'input[name*="addressLine2" i]',
        'input[id*="addressLine2" i]',
    ],
    "city": [
        'input[autocomplete="billing address-level2"]',
        'input[autocomplete="address-level2"]',
        "#billingLocality",
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
        "#billingAdministrativeArea",
        'select[name*="state" i]',
        'input[name*="state" i]',
        'select[id*="state" i]',
        'input[id*="state" i]',
    ],
    "postal_code": [
        'input[autocomplete="billing postal-code"]',
        'input[autocomplete="postal-code"]',
        "#billingPostalCode",
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
        "#billingAddressLine1",
    ],
    "address2": [
        'input[autocomplete="billing address-line2"]',
        'input[autocomplete="address-line2"]',
        "#billingAddressLine2",
    ],
    "city": [
        'input[autocomplete="billing address-level2"]',
        'input[autocomplete="address-level2"]',
        "#billingLocality",
    ],
    "state": [
        'select[autocomplete="billing address-level1"]',
        'input[autocomplete="billing address-level1"]',
        'select[autocomplete="address-level1"]',
        'input[autocomplete="address-level1"]',
        "#billingAdministrativeArea",
    ],
    "postal_code": [
        'input[autocomplete="billing postal-code"]',
        'input[autocomplete="postal-code"]',
        "#billingPostalCode",
    ],
}

PAYPAL_EMAIL_SELECTORS = [
    "input#email",
    'input[name="login_email"]',
    'input[name="email"]',
    'input[type="email"]',
    'input[autocomplete="username"]',
    'input[placeholder*="email" i]',
    'input[aria-label*="email" i]',
]
PAYPAL_PASSWORD_SELECTORS = [
    "input#password",
    "input#password-field",
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
    "#btnNext",
    "#btnLogin",
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
    "#btnNext",
    "#createAccount",
]
PAYPAL_CREATE_ACCOUNT_SELECTORS = [
    "#createAccount",
    "button#createAccount",
    'a[href*="ulOnboardRedirect"]',
    'a[href*="/checkoutweb/signup"]',
    'a:has-text("Create an Account")',
    'button:has-text("Create an Account")',
    'a:has-text("Create account")',
    'button:has-text("Create account")',
    'a:has-text("Sign Up")',
    'button:has-text("Sign Up")',
    'a:has-text("Sign up")',
    'button:has-text("Sign up")',
    'a:has-text("新規登録")',
    'button:has-text("新規登録")',
    'a:has-text("アカウントを作成")',
    'button:has-text("アカウントを作成")',
    'a:has-text("アカウントを開設")',
    'button:has-text("アカウントを開設")',
    'a:has-text("建立帳戶")',
    'button:has-text("建立帳戶")',
    'a:has-text("建立账户")',
    'button:has-text("建立账户")',
    'button:has-text("创建账户")',
    'button:has-text("注册")',
]
PAYPAL_APPROVE_SELECTORS = [
    "#consentButton",
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
PAYPAL_COOKIE_BANNER_DISMISS_SCRIPT = r"""() => {
  const visible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
  const textOf = (node) => String(node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
  const cookieRe = /cookie|cookies|クッキー|プライバシー|privacy|個人情報|personal data/i;
  const closeRe = /^(close|閉じる|关闭|關閉|×|x)$/i;
  const hasCookieMarker = (node) => /cookie|onetrust|privacy|クッキー/i.test([
    node.id || '',
    node.className || '',
    node.getAttribute?.('data-testid') || '',
    node.getAttribute?.('aria-label') || '',
    node.getAttribute?.('role') || '',
  ].join(' '));
  const candidates = Array.from(document.querySelectorAll(
    '[id*="cookie" i], [class*="cookie" i], [data-testid*="cookie" i], [aria-label*="cookie" i], [role="dialog"], [aria-modal="true"], aside, section, div'
  )).filter((node) => {
    if (!visible(node)) return false;
    const text = textOf(node);
    if (!cookieRe.test(text)) return false;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    const fixedLike = style.position === 'fixed' || style.position === 'sticky';
    const modalLike = node.getAttribute?.('role') === 'dialog' || String(node.getAttribute?.('aria-modal') || '').toLowerCase() === 'true';
    const bottomPanel = rect.top > window.innerHeight * 0.45 && rect.bottom > window.innerHeight * 0.72 && rect.height <= window.innerHeight * 0.55;
    return (hasCookieMarker(node) || modalLike || fixedLike || bottomPanel) && rect.width > 180 && rect.height > 40;
  });
  for (const container of candidates) {
    const controls = Array.from(container.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a'))
      .filter(visible)
      .filter((node) => closeRe.test([textOf(node), String(node.value || ''), String(node.getAttribute('aria-label') || '')].join(' ').trim()));
    for (const control of controls) {
      try {
        control.click();
        return { dismissed: true, method: 'click' };
      } catch {}
    }
  }
  const bottomCookie = candidates
    .sort((a, b) => (b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom))[0];
  if (bottomCookie) {
    bottomCookie.setAttribute('data-autotoken-hidden', 'paypal-cookie-banner');
    bottomCookie.style.setProperty('display', 'none', 'important');
    bottomCookie.style.setProperty('pointer-events', 'none', 'important');
    return { dismissed: true, method: 'hide' };
  }
  return { dismissed: false };
}"""
PAYPAL_COOKIE_BANNER_ACCEPT_SELECTORS = [
    'div:has-text("Cookie") button:has-text("Close")',
    '[role="dialog"]:has-text("Cookie") button:has-text("Close")',
    '[role="dialog"]:has-text("Cookie") [role="button"]:has-text("Close")',
    '[role="dialog"]:has-text("Cookie") button[aria-label*="close" i]',
    '[role="dialog"]:has-text("Cookie") [role="button"][aria-label*="close" i]',
    '[role="dialog"]:has-text("クッキー") button:has-text("閉じる")',
    '[role="dialog"]:has-text("プライバシー") button:has-text("閉じる")',
    'div:has-text("Cookie") button[aria-label*="close" i]',
    'div:has-text("クッキー") button:has-text("閉じる")',
    'div:has-text("プライバシー") button:has-text("閉じる")',
]
PAYPAL_SIGNUP_SUBMIT_CLICK_SCRIPT = r"""() => {
  const now = Date.now();
  const lastClickedAt = Number(window.__autotokenPayPalSignupSubmitClickedAt || 0);
  if (lastClickedAt && now - lastClickedAt < 15000) {
    return { clicked: false, skipped: true, reason: 'recent_submit' };
  }
  const visible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
  const textOf = (node) => String(node?.innerText || node?.textContent || node?.value || node?.getAttribute?.('aria-label') || '')
    .replace(/\s+/g, ' ')
    .trim();
  const submitRe = /agree\s*&?\s*continue|agree\s*&?\s*create account|create account|continue payment|同意して続行|同意して続ける|続行|アカウントを作成|创建账户|建立帳戶|继续付款|繼續付款/i;
  const blockedRe = /login|ログイン|cancel|キャンセル|戻る|back|english|利用しない|保存|close/i;
  const nodes = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a'));
  const matches = nodes
    .filter(visible)
    .map((node) => ({ node, text: textOf(node), rect: node.getBoundingClientRect() }))
    .filter((item) => submitRe.test(item.text) && !blockedRe.test(item.text))
    .sort((a, b) => (b.rect.width * b.rect.height - a.rect.width * a.rect.height) || (b.rect.top - a.rect.top));
  for (const item of matches) {
    try {
      item.node.scrollIntoView({ block: 'center', inline: 'nearest' });
      window.__autotokenPayPalSignupSubmitClickedAt = now;
      item.node.click();
      return { clicked: true, text: item.text };
    } catch {}
  }
  return { clicked: false };
}"""
PAYPAL_SIGNUP_SUBMIT_MARK_SCRIPT = r"""() => {
  window.__autotokenPayPalSignupSubmitClickedAt = Date.now();
  return true;
}"""
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
    'input[placeholder*="カード番号"]',
    'input[aria-label*="カード番号"]',
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
    'input[placeholder*="有効期限"]',
    'input[aria-label*="有効期限"]',
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
    'input[placeholder*="セキュリティコード"]',
    'input[aria-label*="セキュリティコード"]',
    'input[id*="cvv" i]',
    'input[name*="cvv" i]',
]
PAYPAL_FIRST_NAME_SELECTORS = [
    "input#firstName",
    'input[name="firstName"]',
    'input[autocomplete="given-name"]',
    'input[placeholder*="first name" i]',
    'input[aria-label*="first name" i]',
    'input[placeholder="名"]',
    'input[aria-label="名"]',
]
PAYPAL_LAST_NAME_SELECTORS = [
    "input#lastName",
    'input[name="lastName"]',
    'input[autocomplete="family-name"]',
    'input[placeholder*="last name" i]',
    'input[aria-label*="last name" i]',
    'input[placeholder="姓"]',
    'input[aria-label="姓"]',
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
    'input[placeholder*="住所"]',
    'input[aria-label*="住所"]',
]
PAYPAL_BILLING_CITY_SELECTORS = [
    "input#billingCity",
    "input#city",
    'input[name="billingCity"]',
    'input[name="city"]',
    'input[autocomplete="address-level2"]',
    'input[autocomplete*="address-level2" i]',
    'input[placeholder*="city" i]',
    'input[aria-label*="city" i]',
    'input[placeholder*="市区町村"]',
    'input[aria-label*="市区町村"]',
    'input[placeholder*="市区郡"]',
    'input[aria-label*="市区郡"]',
]
PAYPAL_BILLING_POSTAL_SELECTORS = [
    "input#billingPostalCode",
    "input#zip",
    "input#postalCode",
    'input[name="billingPostalCode"]',
    'input[name="zip"]',
    'input[name="postalCode"]',
    'input[autocomplete="postal-code"]',
    'input[autocomplete*="postal-code" i]',
    'input[placeholder*="zip" i]',
    'input[aria-label*="zip" i]',
    'input[placeholder*="postal" i]',
    'input[aria-label*="postal" i]',
    'input[placeholder*="郵便番号"]',
    'input[aria-label*="郵便番号"]',
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
    'select[autocomplete*="address-level1" i]',
    'input[autocomplete*="address-level1" i]',
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
    'button:has-text("同意して続行")',
    'button:has-text("同意して続ける")',
    'button:has-text("Continue Payment")',
    'button:has-text("继续付款")',
    'button:has-text("繼續付款")',
    'button:has-text("创建账户")',
    'button:has-text("建立帳戶")',
    'button[type="submit"]',
]
PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS = payment_checkout_browser_service.PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS
PAYPAL_DISMISS_PROMPT_SELECTORS = [
    'button:has-text("OK")',
    'button:has-text("Ok")',
    'button:has-text("Okay")',
    'button:has-text("Not now")',
    'button:has-text("Maybe later")',
    'button:has-text("Skip")',
    'button:has-text("Try another way")',
    'button:has-text("Use password instead")',
    'button:has-text("利用しない")',
    'button:has-text("閉じる")',
    'button:has-text("以后再说")',
    'button:has-text("暂不")',
    'button:has-text("改用密码")',
    '[role="dialog"] button:has-text("利用しない")',
    '[role="dialog"] button:has-text("OK")',
]
PAYPAL_CHECKOUT_SELECTORS = [
    '[data-testid="paypal-accordion-item-button"]',
    'label[for="payment-method-accordion-item-title-paypal"]',
    "#payment-method-accordion-item-title-paypal",
    ".paypal-accordion-item button",
    'button:has-text("PayPal")',
    'label:has-text("PayPal")',
    '[role="button"]:has-text("PayPal")',
    '[role="radio"]:has-text("PayPal")',
    '[aria-label*="paypal" i]',
    'img[alt*="paypal" i]',
]
PAYPAL_CHECKOUT_STATE_SELECTORS = [
    "#payment-method-accordion-item-title-paypal",
    'input[type="radio"][id*="paypal" i]',
    'input[type="radio"][name*="payment" i][value*="paypal" i]',
    '[role="radio"][aria-label*="paypal" i]',
]
CHECKOUT_SUBMIT_SELECTORS = [
    'button[data-testid="submit-button"]',
    'button[data-testid="hosted-payment-submit-button"]',
    'button[data-atomic-wait-intent="Submit_Email"]',
    "button.SubmitButton--complete",
    'button:has-text("Subscribe")',
    'button:has-text("Pay")',
    'button:has-text("Continue")',
    'button:has-text("Agree")',
    'button:has-text("订阅")',
    'button[type="submit"]',
]

PAYPAL_AUTO_STAGE_MESSAGES = paypal_task_payloads_service.PAYPAL_AUTO_STAGE_MESSAGES


def classify_paypal_checkout_state(url: str, body_text: str):
    return payment_checkout_state_service.classify_paypal_checkout_state(url, body_text)


def _classify_paypal_stripe_payment_page(payload: dict[str, Any] | None):
    return payment_checkout_state_service.classify_paypal_stripe_payment_page(payload)


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
            f"{stage} 返回非 JSON: HTTP {getattr(resp, 'status_code', '?')} {(getattr(resp, 'text', '') or '')[:300]}"
        ) from exc
    return payload if isinstance(payload, dict) else {"_raw": payload}


def _protocol_ensure_ok(resp: Any, stage: str) -> dict:
    status_code = int(getattr(resp, "status_code", 0) or 0)
    if 200 <= status_code < 300:
        return _protocol_http_json(resp, stage)
    text = str(getattr(resp, "text", "") or "")
    lowered = text.lower()
    if payment_checkout_state_service.paypal_risk_challenge_text_hint(text):
        raise RuntimeError(f"{stage} 被 PayPal/Stripe 风控拦截，需要切换浏览器模式或人工处理: HTTP {status_code}")
    if stage == "paypal_protocol_confirm" and "payment_method_types_mismatch" in lowered:
        raise RuntimeError(
            f"{stage} 失败: 当前 checkout session 未启用 PayPal 支付方式，"
            "请重新生成支持 PayPal 的 US/USD checkout 后再走协议无卡流程"
        )
    raise RuntimeError(f"{stage} 失败: HTTP {status_code} {text[:500]}")


def _paypal_protocol_elements_options() -> dict[str, str]:
    return paypal_billing_agreement_service.paypal_protocol_elements_options()


def _paypal_protocol_checkout_amount(payload: dict) -> str:
    return paypal_billing_agreement_service.paypal_protocol_checkout_amount(payload)


def _paypal_protocol_amount_due(value: Any) -> int:
    return paypal_billing_agreement_service.paypal_protocol_amount_due(value)


def _paypal_protocol_payment_method_types(payload: Any) -> set[str]:
    return paypal_billing_agreement_service.paypal_protocol_payment_method_types(payload)


STRIPE_VERSION_BASE = "2025-03-31.basil"


def _paypal_protocol_stripe_init(http: Any, checkout_session_id: str, stripe_pk: str) -> dict:
    stripe_js_id = str(uuid.uuid4())
    elements_session_id = f"elements_session_{uuid.uuid4().hex[:11]}"
    elements_options = _paypal_protocol_elements_options()
    url = f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/init"

    # Browser custom checkout uses the beta/manual-approval version first.
    # Keep the base version as a compatibility fallback for older sessions.
    for version, include_betas in [
        (STRIPE_VERSION_FULL, True),
        (STRIPE_VERSION_BASE, False),
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
                "payment_method_types": _paypal_protocol_payment_method_types(payload),
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
    payment_method_types = ["card", "link", "paypal"]
    params = {
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": str(int(re.sub(r"\D+", "", str(init_ctx.get("expected_amount") or "0")) or "0")),
        "deferred_intent[currency]": str(init_ctx.get("currency") or "usd").lower(),
        "deferred_intent[setup_future_usage]": "off_session",
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
    for index, payment_method_type in enumerate(payment_method_types):
        params[f"deferred_intent[payment_method_types][{index}]"] = payment_method_type
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


def _paypal_protocol_update_payment_page_address(
    http: Any, checkout_session_id: str, stripe_pk: str, init_ctx: dict, billing: dict[str, str]
) -> None:
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    base = {
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": init_ctx.get("elements_session_id")
        or f"elements_session_{uuid.uuid4().hex[:11]}",
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
            logger.info(
                "[paypal_protocol] address update soft-failed: HTTP %s %s", resp.status_code, (resp.text or "")[:180]
            )
    except Exception as exc:
        logger.info("[paypal_protocol] address update soft-failed: %s", exc)


def _paypal_protocol_create_payment_method(
    http: Any, checkout_session_id: str, stripe_pk: str, init_ctx: dict, billing: dict[str, str], email: str
) -> str:
    runtime = _stripe_runtime_from_env()
    runtime_version = runtime.get("version") or DEFAULT_STRIPE_RUNTIME_VERSION
    effective_version = init_ctx.get("stripe_version") or STRIPE_VERSION_FULL
    data = {
        "type": "paypal",
        "billing_details[name]": billing.get("name") or DEFAULT_PAYPAL_NAME,
        "billing_details[email]": email or billing.get("email") or "buyer@example.com",
        "billing_details[phone]": billing.get("phone") or "",
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
        "client_attribution_metadata[checkout_config_id]": init_ctx.get("payment_method_checkout_config_id")
        or init_ctx.get("config_id")
        or "",
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


def _paypal_protocol_confirm_checkout(
    http: Any,
    _checkout_url: str,
    checkout_session_id: str,
    stripe_pk: str,
    init_ctx: dict,
    payment_method_id: str,
    extra_data: dict[str, str] | None = None,
) -> dict:
    processor_entity = str(init_ctx.get("processor_entity") or "openai_llc")
    checkout_country = str(init_ctx.get("billing_country") or ("US" if processor_entity == "openai_llc" else "FR"))
    chatgpt_return = (
        f"https://chatgpt.com/checkout/verify?stripe_session_id={checkout_session_id}"
        f"&processor_entity={processor_entity}&plan_type=plus"
    )
    return_url = (
        f"https://checkout.stripe.com/c/pay/{checkout_session_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url={quote(chatgpt_return, safe='')}"
    )
    if init_ctx.get("stripe_hosted_url"):
        return_url = _paypal_opll_confirm_return_url(
            checkout_session_id,
            {"billing_country": checkout_country, "processor_entity": processor_entity},
            str(init_ctx.get("stripe_hosted_url") or ""),
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
    if extra_data:
        data.update(extra_data)
    resp = http.post(f"{STRIPE_API}/v1/payment_pages/{checkout_session_id}/confirm", data=data, timeout=30)
    return _protocol_ensure_ok(resp, "paypal_protocol_confirm")


def _paypal_protocol_unescape_url(value: str) -> str:
    return paypal_billing_agreement_service.paypal_protocol_unescape_url(value)


def _paypal_protocol_extract_url_from_text(value: str) -> str:
    return paypal_billing_agreement_service.paypal_protocol_extract_url_from_text(value)


def _paypal_protocol_extract_ba_token(url: str, fallback: str = "") -> str:
    return paypal_billing_agreement_service.paypal_protocol_extract_ba_token(url, fallback=fallback)


def _find_paypal_redirect_url(payload: Any) -> str:
    return paypal_billing_agreement_service.find_paypal_redirect_url(payload)


def _paypal_protocol_resolve_approve_url(http: Any, redirect_url: str) -> tuple[str, str]:
    current = str(redirect_url or "").strip()
    ba_token = ""
    for _ in range(8):
        if not current:
            break
        current = _paypal_protocol_unescape_url(current)
        parsed = urlsplit(current)
        ba_token = _paypal_protocol_extract_ba_token(current, ba_token)
        if _is_paypal_host(current) and (
            "/agreements/approve" in parsed.path
            or "/checkoutweb/signup" in parsed.path
            or (parsed.path == "/pay" and ba_token)
        ):
            return current, ba_token
        host = _safe_host(current)
        if host and not (_is_paypal_host(current) or _is_checkout_host(current) or host.endswith(".stripe.com")):
            break
        try:
            resp = http.get(current, allow_redirects=False, timeout=30)
        except Exception as exc:
            raise RuntimeError(f"解析 PayPal redirect 失败: {exc}") from exc
        text = str(getattr(resp, "text", "") or "")
        if payment_checkout_state_service.paypal_risk_challenge_text_hint(text):
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
        if 200 <= int(getattr(resp, "status_code", 0) or 0) < 300 and _is_paypal_host(current):
            return current, ba_token
        break
    return current, ba_token


def _paypal_protocol_checkout_url_for_wait(
    *,
    checkout_url: str = "",
    hosted_checkout_url: str = "",
    checkout_session_id: str = "",
) -> str:
    for candidate in (checkout_url, hosted_checkout_url):
        if _extract_checkout_session_id(candidate):
            return str(candidate or "")
    session_id = str(checkout_session_id or "").strip()
    if session_id.startswith("cs_"):
        return f"https://pay.openai.com/c/pay/{session_id}"
    return ""


def _paypal_protocol_wait_checkout_result(
    http: Any,
    *,
    checkout_url: str,
    return_url: str = "",
    timeout_seconds: int,
    on_progress=None,
):
    wait_url = _paypal_protocol_checkout_url_for_wait(checkout_url=checkout_url)
    if not wait_url:
        return _build_result(
            "needs_review",
            failure_stage="post_submit",
            message="协议模式已完成 PayPal authorize，但缺少 checkout session，无法确认最终支付状态",
        )
    if return_url:
        try:
            resp = http.get(return_url, timeout=30, allow_redirects=True)
            final_url = str(getattr(resp, "url", "") or "")
            if final_url:
                wait_url = _paypal_protocol_checkout_url_for_wait(
                    checkout_url=final_url,
                    hosted_checkout_url=wait_url,
                )
            try:
                return_payload = resp.json()
            except Exception:
                return_payload = None
            return_state = _classify_paypal_stripe_payment_page(return_payload if isinstance(return_payload, dict) else {})
            if return_state and return_state.get("status") in {"success", "failed"}:
                return return_state
        except Exception as exc:
            logger.info("[paypal_protocol] return_url follow soft-failed: %s", exc)
    deadline = time.time() + max(30, min(int(timeout_seconds or 90), 180))
    last_processing_message = ""
    while time.time() < deadline:
        state = _fetch_paypal_stripe_payment_page_state(wait_url, http=http)
        if state and state.get("status") in {"success", "failed"}:
            return state
        if state and state.get("status") == "needs_review":
            last_processing_message = str(state.get("message") or "")
        _emit_progress(on_progress, _progress_event("paypal_protocol_wait_result", checkout_url=wait_url))
        time.sleep(PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS)
    return _build_result(
        "needs_review",
        failure_stage="post_submit",
        message=last_processing_message or "协议模式已完成 PayPal authorize，但未在时限内确认最终支付状态",
    )


def _paypal_protocol_socks_invalid_response(exc: Exception) -> bool:
    return paypal_proxy_service.paypal_protocol_socks_invalid_response(exc)


def _paypal_protocol_http_proxy_fallback_url(proxy_url: str | None) -> str:
    return paypal_proxy_service.paypal_protocol_http_proxy_fallback_url(proxy_url)


def _paypal_protocol_transient_transport_error(message: str) -> bool:
    return payment_checkout_state_service.paypal_protocol_transient_transport_error(message)


def _run_paypal_protocol_flow(
    *,
    email: str,
    checkout_url: str = "",
    proxy_url: str | None = None,
    paypal_mode: str = "create_account",
    signup_profile: dict[str, str | bool] | None = None,
    phone_accounts: list[dict] | None = None,
    billing_payload: dict[str, str] | None = None,
    timeout_seconds: int = 300,
    paypal_country: str = "US",
    paypal_lang: str = "en",
    is_cancelled=None,
    on_progress=None,
    pre_extracted: dict[str, Any] | None = None,
):
    if callable(is_cancelled) and is_cancelled():
        return _build_result("failed", failure_stage="paypal_protocol", message="任务已取消")
    paypal_country = _normalize_paypal_country(paypal_country)
    paypal_lang = _normalize_paypal_lang(paypal_lang, paypal_country)

    protocol_proxy_url = proxy_url
    http = _new_http_session(protocol_proxy_url, require_curl_cffi=False)
    _emit_progress(on_progress, _progress_event("paypal_protocol_start", message="protocol flow started"))
    # 中间状态追踪，供浏览器降级使用
    _approve_url = ""
    _ba_token = ""
    _payment_method_id = ""

    # ---- Pre-extracted BA link path (pplink-style) ----
    if pre_extracted and paypal_billing_agreement_service.paypal_ba_token_is_valid(
        pre_extracted.get("ba_token")
    ):
        _approve_url = str(pre_extracted.get("approve_url") or "")
        _ba_token = str(pre_extracted.get("ba_token") or "")
        _payment_method_id = str(pre_extracted.get("pm_id") or "")
        checkout_session_id = str(pre_extracted.get("checkout_session_id") or "")
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_protocol_pre_extracted",
                ba_token=_ba_token,
                approve_url=_safe_url_summary(_approve_url),
            ),
        )
        if paypal_mode != "create_account":
            result = _build_result(
                "needs_review",
                failure_stage="paypal_protocol_authorize",
                message="协议模式已生成 PayPal 授权链接；已有账号登录授权暂未接管，请切回浏览器模式或人工完成授权",
            )
            result["paypal_approve_url"] = _approve_url
            result["ba_token"] = _ba_token
            result["payment_method_id"] = _payment_method_id
            return result

        signup_profiles = _paypal_signup_profiles_for_phone_pool(signup_profile, phone_accounts)
        if not signup_profiles and not phone_accounts:
            signup_profiles = [dict(signup_profile or {})]
        if not signup_profiles or not any(
            str(item.get("phone") or "").strip() and str(item.get("sms_url") or "").strip() for item in signup_profiles
        ):
            return _build_result(
                "failed",
                failure_stage="paypal_protocol",
                message="协议模式自动注册需要可用手机号和接码 API",
            )
        billing_payload = dict(billing_payload or {})
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
                _new_paypal_protocol_http_session(protocol_proxy_url),
                ba_token=_ba_token,
                approve_url=_approve_url,
                signup_profile=current_profile,
                timeout_seconds=max(90, timeout_seconds),
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                locale_country=str(current_profile.get("country") or billing_payload.get("country") or paypal_country)
                .strip()
                .upper()
                or paypal_country,
                locale_lang=paypal_lang,
            )
            protocol_signup_result["paypal_approve_url"] = _approve_url
            protocol_signup_result["ba_token"] = protocol_signup_result.get("ba_token") or _ba_token
            protocol_signup_result["payment_method_id"] = _payment_method_id
            last_result = protocol_signup_result
            if protocol_signup_result.get("failure_stage") == "paypal_phone_rejected" and signup_index < len(
                signup_profiles
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
                checkout_url_for_wait = _paypal_protocol_checkout_url_for_wait(
                    checkout_url=str(pre_extracted.get("checkout_url") or ""),
                    hosted_checkout_url=str(pre_extracted.get("hosted_checkout_url") or ""),
                    checkout_session_id=checkout_session_id,
                )
                wait_result = _paypal_protocol_wait_checkout_result(
                    http,
                    checkout_url=checkout_url_for_wait,
                    return_url=str(protocol_signup_result.get("return_url") or ""),
                    timeout_seconds=max(60, min(timeout_seconds, 180)),
                    on_progress=on_progress,
                )
                wait_result["paypal_approve_url"] = _approve_url
                wait_result["ba_token"] = protocol_signup_result.get("ba_token") or _ba_token
                wait_result["payment_method_id"] = _payment_method_id
                wait_result["return_url"] = protocol_signup_result.get("return_url") or ""
                wait_result["paypal_user_id"] = protocol_signup_result.get("paypal_user_id") or ""
                return wait_result
            protocol_signup_result.setdefault("paypal_approve_url", _approve_url)
            protocol_signup_result.setdefault("ba_token", _ba_token)
            protocol_signup_result.setdefault("payment_method_id", _payment_method_id)
            return protocol_signup_result
        last_result.setdefault("paypal_approve_url", _approve_url)
        last_result.setdefault("ba_token", _ba_token)
        last_result.setdefault("payment_method_id", _payment_method_id)
        return last_result

    # ---- Original Stripe protocol path (legacy fallback) ----
    checkout_session_id = _extract_checkout_session_id(checkout_url or "")
    if not checkout_session_id:
        return _build_result("failed", failure_stage="paypal_protocol", message="协议模式无法识别 checkout session id")
    billing_payload = dict(billing_payload or {})
    if not _has_complete_billing_payload(billing_payload):
        return _build_result("failed", failure_stage="paypal_protocol", message="协议模式账单地址缺少必要字段")
    paypal_country = _normalize_paypal_country(paypal_country or str(billing_payload.get("country") or "US"))
    _emit_progress(on_progress, _progress_event("paypal_protocol_start", checkout_session_id=checkout_session_id))
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
        _paypal_protocol_update_payment_page_address(
            http, checkout_session_id, DEFAULT_STRIPE_PK, init_ctx, billing_payload
        )
        payment_method_id = _paypal_protocol_create_payment_method(
            http,
            checkout_session_id,
            DEFAULT_STRIPE_PK,
            init_ctx,
            billing_payload,
            email,
        )
        _emit_progress(
            on_progress, _progress_event("paypal_protocol_payment_method", payment_method_id=payment_method_id)
        )
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
        if not signup_profiles and not phone_accounts:
            signup_profiles = [dict(signup_profile or {})]
        if not signup_profiles or not any(
            str(item.get("phone") or "").strip() and str(item.get("sms_url") or "").strip() for item in signup_profiles
        ):
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
                _new_paypal_protocol_http_session(protocol_proxy_url),
                ba_token=ba_token,
                approve_url=approve_url,
                signup_profile=current_profile,
                timeout_seconds=max(90, timeout_seconds),
                is_cancelled=is_cancelled,
                on_progress=on_progress,
                locale_country=str(current_profile.get("country") or billing_payload.get("country") or paypal_country)
                .strip()
                .upper()
                or paypal_country,
                locale_lang=paypal_lang,
            )
            protocol_signup_result["paypal_approve_url"] = approve_url
            protocol_signup_result["ba_token"] = protocol_signup_result.get("ba_token") or ba_token
            protocol_signup_result["payment_method_id"] = payment_method_id
            last_result = protocol_signup_result
            if protocol_signup_result.get("failure_stage") == "paypal_phone_rejected" and signup_index < len(
                signup_profiles
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
    return payment_checkout_state_service.paypal_protocol_needs_browser_fallback(result)


def _safe_host(url: str) -> str:
    return payment_checkout_state_service.safe_host(url)


def _is_paypal_host(url: str) -> bool:
    return payment_checkout_state_service.is_paypal_host(url)


def _paypal_stop_before_signup_otp_enabled() -> bool:
    return paypal_preflight_service.paypal_stop_before_signup_otp_enabled(
        os.environ.get("AUTOTOKEN_PAYPAL_STOP_BEFORE_SIGNUP_OTP")
    )


def _paypal_create_account_entry_url(
    url: str,
    *,
    ba_token: str = "",
    country: str = "US",
    lang: str = "en",
) -> str:
    return paypal_billing_agreement_service.paypal_create_account_entry_url(
        url,
        ba_token=ba_token,
        country=country,
        lang=lang,
    )


def _goto_paypal_create_account_entry(
    api: ChatGPTTeamAPI,
    *,
    ba_token: str = "",
    country: str = "US",
    lang: str = "en",
    on_progress=None,
) -> bool:
    next_url = _paypal_create_account_entry_url(
        str(getattr(api.page, "url", "") or ""),
        ba_token=ba_token,
        country=country,
        lang=lang,
    )
    if not next_url:
        return False
    current_url = str(getattr(api.page, "url", "") or "")
    if next_url == current_url:
        return False
    _emit_progress(
        on_progress,
        _progress_event(
            "paypal_create_account",
            "PayPal 登录页已切换到开户注册入口",
            url=_safe_url_summary(next_url),
        ),
    )
    try:
        api.page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        try:
            api.page.wait_for_timeout(1500)
        except Exception:
            time.sleep(1.5)
        return True
    except Exception as exc:
        logger.info("[paypal_bind_executor] PayPal create-account redirect failed: %s", exc)
        return False


def _goto_paypal_page_with_retries(
    page,
    url: str,
    *,
    on_progress=None,
    attempts: int = 3,
    timeout_ms: int = 60000,
) -> None:
    target_url = str(url or "").strip()
    max_attempts = max(1, int(attempts or 1))
    transient_markers = (
        "err_connection_aborted",
        "err_connection_reset",
        "err_tunnel_connection_failed",
        "err_proxy_connection_failed",
        "net::err",
        "timeout",
        "target page, context or browser has been closed",
    )
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            return
        except Exception as exc:
            last_exc = exc
            message = str(exc or "")
            if attempt >= max_attempts or not any(marker in message.lower() for marker in transient_markers):
                raise
            logger.info(
                "[paypal_bind_executor] PayPal navigation transient failure, retrying %s/%s: %s",
                attempt + 1,
                max_attempts,
                _safe_error_summary(exc),
            )
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_browser_navigation_retry",
                    f"PayPal 页面打开失败，正在重试 {attempt + 1}/{max_attempts}: {_safe_error_summary(exc)}",
                    level="warn",
                ),
            )
            try:
                page.wait_for_timeout(1500)
            except Exception:
                time.sleep(1.5)
    if last_exc is not None:
        raise last_exc


def _is_paypal_ssl_protocol_error_page(url: str, body_text: str = "") -> bool:
    return payment_checkout_state_service.is_paypal_ssl_protocol_error_page(url, body_text)


def _is_checkout_host(url: str) -> bool:
    return payment_checkout_state_service.is_checkout_host(url)


def _is_chatgpt_or_openai_return_url(url: str) -> bool:
    return payment_checkout_state_service.is_chatgpt_or_openai_return_url(url)


def _autofill_allowed(url: str) -> bool:
    return payment_checkout_state_service.paypal_autofill_allowed(url)


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
    return payment_form_fields_service.normalize_paypal_credentials(email, password)


def _normalize_paypal_mode(mode: str = "") -> str:
    return paypal_preflight_service.normalize_paypal_mode_legacy(mode)


def _generate_random_paypal_email() -> str:
    return payment_form_fields_service.generate_random_paypal_email(uuid_hex=uuid.uuid4().hex)


def _generate_random_paypal_password() -> str:
    return payment_form_fields_service.generate_random_paypal_password(
        choose=secrets.choice,
        shuffle=secrets.SystemRandom().shuffle,
    )


def _split_paypal_name(name: str) -> tuple[str, str]:
    return payment_form_fields_service.split_paypal_name(name)


def _normalize_paypal_phone(phone: str) -> str:
    return payment_form_fields_service.normalize_paypal_phone(phone)


def _paypal_phone_value_valid(phone: str, *, country: str = "") -> bool:
    return payment_form_fields_service.paypal_phone_value_valid(
        phone,
        country=country,
        normalize_country=_normalize_paypal_country,
        normalize_phone=_normalize_paypal_phone,
    )


def _normalize_paypal_card_expiry(value: str) -> str:
    return payment_form_fields_service.normalize_paypal_card_expiry(value)


def _luhn_check_digit(prefix: str) -> str:
    return payment_form_fields_service.luhn_check_digit(prefix)


def _is_luhn_valid(value: str) -> bool:
    return payment_form_fields_service.luhn_valid(value)


def _paypal_card_brand_allowed(value: str) -> bool:
    return payment_form_fields_service.paypal_card_brand_allowed(value)


def _generate_paypal_card_number() -> str:
    return payment_form_fields_service.generate_paypal_card_number(choose=secrets.choice)


def _normalize_or_generate_paypal_card_number(value: str) -> str:
    return payment_form_fields_service.normalize_or_generate_paypal_card_number(
        value,
        generate_card_number=_generate_paypal_card_number,
    )


def _generate_paypal_card_expiry() -> str:
    return payment_form_fields_service.generate_paypal_card_expiry(randbelow=secrets.randbelow)


def _generate_paypal_card_cvv(card_number: str = "") -> str:
    return payment_form_fields_service.generate_paypal_card_cvv(card_number, choose=secrets.choice)


def _first_payload_value(source: dict, *keys: str) -> str:
    return payment_form_fields_service.first_payload_value(source, *keys)


def _split_paypal_address_lines(address1: str) -> tuple[str, str]:
    return payment_form_fields_service.split_paypal_address_lines(address1)


def _flatten_paypal_generator_fields(value, prefix: str = "") -> dict[str, str]:
    return payment_form_fields_service.flatten_paypal_generator_fields(value, prefix)


def _paypal_generator_field(address: dict, *names: str) -> str:
    return payment_form_fields_service.paypal_generator_field(address, *names)


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
    card_cvv = _paypal_generator_field(
        address, "CVV2", "CVV", "CVC", "Security_Code", "Credit_Card_CVV", "Credit Card CVV"
    )
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


def _paypal_requests_proxy_map(proxy_url: str | None) -> dict[str, str]:
    return paypal_proxy_service.paypal_requests_proxy_map(proxy_url)


def _paypal_proxy_exit_location(proxy_url: str | None) -> dict[str, str]:
    return paypal_proxy_service.paypal_proxy_exit_location(
        proxy_url,
        on_error=lambda exc: logger.info(
            "[paypal_bind_executor] proxy exit geo probe unavailable: %s",
            _safe_error_summary(exc),
        ),
    )


def _mockaddress_jp_json(cache_key: str, url: str) -> dict:
    return paypal_mockaddress_service.mockaddress_jp_json(
        _MOCKADDRESS_JP_CACHE,
        cache_key,
        url,
        on_error=lambda exc: logger.info(
            "[paypal_bind_executor] MockAddress JP data unavailable: %s",
            _safe_error_summary(exc),
        ),
    )


def _jp_prefecture_key_from_text(value: str) -> str:
    return paypal_mockaddress_service.jp_prefecture_key_from_text(
        value,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )


def _jp_prefecture_key_for_proxy(proxy_url: str | None) -> tuple[str, dict[str, str]]:
    exit_location = _paypal_proxy_exit_location(proxy_url)
    key, exit_location, non_jp_exit = paypal_mockaddress_service.jp_prefecture_key_for_exit_location(
        exit_location,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )
    if non_jp_exit:
        logger.info(
            "[paypal_bind_executor] PayPal JP signup proxy exit is not Japan: country=%s region=%s city=%s ip=%s",
            exit_location.get("country_code") or "",
            exit_location.get("region") or "",
            exit_location.get("city") or "",
            exit_location.get("ip") or "",
        )
        return "", exit_location
    return key, exit_location


def _format_jp_postcode(value: Any) -> str:
    return paypal_mockaddress_service.format_jp_postcode(value)


def _random_jp_phone_number(prefecture: dict[str, Any] | None = None) -> str:
    return paypal_mockaddress_service.random_jp_phone_number(
        prefecture,
        choose=random.choice,
        randint=random.randint,
    )


def _mockaddress_name_list(value: Any) -> list[str]:
    return paypal_mockaddress_service.mockaddress_name_list(value)


def _fetch_mockaddress_jp_name_profile() -> dict[str, str]:
    jp_names = _mockaddress_jp_json("jp_names", MOCKADDRESS_JP_NAMES_DATA_URL)
    global_names = _mockaddress_jp_json("global_names", MOCKADDRESS_NAMES_DATA_URL)
    return paypal_mockaddress_service.build_mockaddress_jp_name_profile(
        jp_names,
        global_names,
        default_native_first_name=DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME,
        default_native_last_name=DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME,
        random_float=random.random,
        randrange=random.randrange,
        choose=random.choice,
    )


def _fetch_mockaddress_jp_billing_profile(*, proxy_url: str | None = None) -> dict:
    data = _mockaddress_jp_json("jp_data", MOCKADDRESS_JP_DATA_URL)
    real_areas = _mockaddress_jp_json("jp_real_areas", MOCKADDRESS_JP_REAL_AREAS_URL)
    prefectures = paypal_mockaddress_service.mockaddress_jp_prefectures(data)
    if not prefectures:
        return dict(DEFAULT_PAYPAL_JP_BILLING_PROFILE)

    prefecture_key, exit_location = _jp_prefecture_key_for_proxy(proxy_url)
    prefecture_key = paypal_mockaddress_service.select_mockaddress_jp_prefecture_key(prefectures, prefecture_key)
    generated_name = _fetch_mockaddress_jp_name_profile()
    profile = paypal_mockaddress_service.build_mockaddress_jp_billing_profile(
        data,
        real_areas,
        prefecture_key=prefecture_key,
        exit_location=exit_location,
        generated_name=generated_name,
        default_name=DEFAULT_PAYPAL_NAME,
        default_native_first_name=DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME,
        default_native_last_name=DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME,
        default_billing_profile=DEFAULT_PAYPAL_JP_BILLING_PROFILE,
        choose=random.choice,
        randint=random.randint,
    )

    logger.info(
        "[paypal_bind_executor] PayPal JP signup address generated: prefecture=%s city=%s zip=%s proxy_country=%s proxy_region=%s proxy_city=%s",
        profile.get("state") or "",
        profile.get("city") or "",
        profile.get("zip") or "",
        exit_location.get("country_code") or "",
        exit_location.get("region") or "",
        exit_location.get("city") or "",
    )
    return profile


def _prepare_paypal_signup_billing_payload(
    billing_payload: dict[str, str] | None,
    *,
    paypal_country: str,
    proxy_url: str | None = None,
    auto_generate: bool = False,
) -> dict[str, str]:
    return paypal_mockaddress_service.prepare_paypal_jp_signup_billing_payload(
        billing_payload,
        paypal_country=paypal_country,
        auto_generate=auto_generate,
        normalize_country=_normalize_paypal_country,
        billing_payload_complete=_has_complete_billing_payload,
        fetch_generated_billing_profile=lambda: _fetch_mockaddress_jp_billing_profile(proxy_url=proxy_url),
        default_name=DEFAULT_PAYPAL_NAME,
        default_native_first_name=DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME,
        default_native_last_name=DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME,
        default_billing_profile=DEFAULT_PAYPAL_JP_BILLING_PROFILE,
    )


def _public_paypal_billing_info(billing: dict | None) -> dict:
    return payment_form_fields_service.public_paypal_billing_info(billing)


def _build_paypal_signup_profile(
    *,
    paypal_email: str = "",
    paypal_password: str = "",
    billing_payload: dict[str, str] | None = None,
    paypal_country: str = "",
    sms_url: str = "",
    otp_channel: str = "sms",
    phone_accounts: list[dict] | None = None,
    paypal_card_number: str = "",
    paypal_card_expiry: str = "",
    paypal_card_cvv: str = "",
) -> dict[str, str | bool]:
    # Kept for call-site parity; phone pools are expanded after the base profile is built.
    _ = phone_accounts
    return payment_form_fields_service.build_paypal_signup_profile(
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        billing_payload=billing_payload,
        paypal_country=paypal_country,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        country_billing_profiles=DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES,
        normalize_country=_normalize_paypal_country,
        generate_email=_generate_random_paypal_email,
        generate_password=_generate_random_paypal_password,
        normalize_or_generate_card_number=_normalize_or_generate_paypal_card_number,
        generate_card_expiry=_generate_paypal_card_expiry,
        generate_card_cvv=_generate_paypal_card_cvv,
    )


def _normalize_paypal_phone_account(raw: Any, *, fallback_otp_channel: str = "sms") -> dict[str, str]:
    return payment_form_fields_service.normalize_paypal_phone_account(
        raw,
        fallback_otp_channel=fallback_otp_channel,
    )


def _paypal_signup_profiles_for_phone_pool(
    base_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None,
) -> list[dict[str, str | bool]]:
    return payment_form_fields_service.paypal_signup_profiles_for_phone_pool(
        base_profile,
        phone_accounts,
        normalize_phone=_normalize_paypal_phone,
        phone_value_valid=_paypal_phone_value_valid,
    )


def _build_checkout_billing_payload(payload: dict | None) -> dict[str, str]:
    normalized = normalize_autofill_payload(payload)
    return payment_form_fields_service.build_paypal_checkout_billing_payload(normalized)


def _merge_checkout_billing_payload(payload: dict | None) -> dict[str, str]:
    requested = _build_checkout_billing_payload(payload)
    requested_country = _normalize_paypal_country(requested.get("country") or "US")
    if requested_country in DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES:
        generated_raw = dict(DEFAULT_PAYPAL_COUNTRY_BILLING_PROFILES[requested_country])
    else:
        requested_country = "US"
        generated_raw = _fetch_paypal_random_billing_profile()
    return payment_form_fields_service.merge_paypal_checkout_billing_payload(
        requested,
        generated_raw,
        requested_country=requested_country,
        default_name=DEFAULT_PAYPAL_NAME,
        normalize_or_generate_card_number=_normalize_or_generate_paypal_card_number,
        generate_card_expiry=_generate_paypal_card_expiry,
        generate_card_cvv=_generate_paypal_card_cvv,
    )


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
    return payment_form_fields_service.paypal_billing_payload_complete(payload)


def _paypal_hosted_captcha_bypass_function_source() -> str:
    return payment_checkout_browser_service.paypal_hosted_captcha_bypass_function_source(
        PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS
    )


def _ensure_paypal_hosted_captcha_bypass(api: ChatGPTTeamAPI) -> bool:
    context = getattr(api, "context", None)
    page = getattr(api, "page", None)
    if not context or not page:
        return False

    script = _paypal_hosted_captcha_bypass_function_source()
    if not getattr(api, "_paypal_hosted_captcha_bypass_installed", False):
        try:
            context.add_init_script(script=f"({script})();")
            api._paypal_hosted_captcha_bypass_installed = True
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


def _is_ddc_blocked_page(page) -> bool:
    """检测 DataDome 'You have been blocked' 拦截页面。"""
    try:
        text = page.inner_text("body")[:3000]
    except Exception:
        return False
    return payment_checkout_state_service.datadome_blocked_text_hint(text)


def _is_ddc_frame_url(url: str) -> bool:
    """DataDome frame URL 判断。避免把普通 captcha/hCaptcha iframe 误判成 DDC。"""
    return payment_checkout_state_service.is_datadome_frame_url(url)


def _ddc_slider_visible(page) -> bool:
    """检测主文档 + DataDome iframe 中是否有滑块可见。"""
    try:
        pt = page.inner_text("body")[:2000]
        if payment_checkout_state_service.datadome_slider_text_hint(pt):
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
        if payment_checkout_state_service.datadome_slider_text_hint(txt):
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
            ".slider",
            '[role="slider"]',
            ".slider-handle",
            ".sliderIcon",
            'div[class*="slider"]',
            'button[class*="slider"]',
            "#ddv1-captcha-container .slider",
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
            attempt + 1,
            start_x,
            start_y,
            end_x,
            end_y,
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
                    logger.info(
                        "[paypal_ddc] confirmed blocked page after slider gone (%d, attempt %d)",
                        _check_i + 1,
                        attempt + 1,
                    )
                    return False
                cur = page.url
                if any(kw in cur for kw in ("/webapps/hermes", "checkoutweb", "/signin", "chatgpt.com")):
                    logger.info("[paypal_ddc] slider passed → %s", cur[:80])
                    return True
                if (
                    page.query_selector('input[name="login_email"]')
                    or page.query_selector("#consentButton")
                    or page.query_selector('[data-testid="email"]')
                    or page.query_selector('[data-testid="createAccount"]')
                ):
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

        cur = page.url
        if any(kw in cur for kw in ["/signin", "/authflow", "/webapps/hermes", "/pay", "chatgpt.com", "/checkoutweb"]):
            logger.info("[paypal_ddc] DDC passed → %s", cur[:80])
            return True

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
                if any(
                    kw in cur
                    for kw in ["/signin", "/authflow", "/webapps/hermes", "/pay", "chatgpt.com", "/checkoutweb"]
                ):
                    logger.info("[paypal_ddc] DDC passed → %s", cur[:80])
                    return True
                # 检测到 PayPal 表单元素
                if (
                    page.query_selector('input[name="login_email"]')
                    or page.query_selector("#consentButton")
                    or page.query_selector('[data-testid="email"]')
                ):
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
                retry_btn = page.query_selector('button:has-text("重试")') or page.query_selector(
                    'button:has-text("Retry")'
                )
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
            _emit_progress(
                on_progress,
                _progress_event(
                    "paypal_ddc_blocked_final",
                    f"DataDome blocked 页面重试 {max_blocked_retries} 次仍未通过",
                ),
            )
            return False
        logger.info(
            "[paypal_ddc] blocked page detected, refreshing (retry %d/%d)...", blocked_retries, max_blocked_retries
        )
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_ddc_blocked_retry",
                f"DataDome 封锁页面，正在刷新重试 ({blocked_retries}/{max_blocked_retries})",
            ),
        )
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            logger.info("[paypal_ddc] reload failed: %s", exc)
        time.sleep(_random.uniform(3.0, 5.0))


def _visible_locator_in_frames(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 1000):
    return payment_form_fields_service.visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms)


def _iter_page_frames(api: ChatGPTTeamAPI):
    return payment_checkout_browser_service.iter_page_frames(api)


def _attached_locator_in_frames(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 500):
    return payment_form_fields_service.attached_locator_in_frames(
        _iter_page_frames(api),
        selectors,
        timeout_ms=timeout_ms,
    )


def _set_locator_value(locator, value: str) -> bool:
    return payment_form_fields_service.set_locator_value(
        locator,
        value,
        prefer_select_option=True,
        fill_fallback=True,
        legacy_dispatch_arg=True,
    )


def _set_paypal_state_locator_value(locator, value: str, *, country: str = "") -> bool:
    return payment_form_fields_service.select_state_locator_value(
        locator,
        value,
        country=country,
        normalize_country=_normalize_paypal_country,
        jp_prefecture_candidates=_jp_prefecture_candidates,
        set_value=_set_locator_value,
    )


def _type_locator_value(locator, value: str) -> bool:
    return payment_form_fields_service.type_locator_value(locator, value)


def _dispatch_locator_value(locator, value: str) -> bool:
    return payment_form_fields_service.dispatch_locator_value(locator, value, legacy_value_arg=True)


def _read_locator_value(locator) -> str:
    return payment_form_fields_service.read_locator_value(locator, prefer_select_text=True)


def _value_matches(expected: str, actual: str) -> bool:
    return payment_form_fields_service.value_matches(expected, actual)


def _normalize_us_state_value(value: str) -> str:
    return payment_form_fields_service.normalize_us_state_value(
        value,
        state_name_to_code=US_STATE_NAME_TO_CODE,
        state_code_to_name=US_STATE_CODE_TO_NAME,
    )


def _jp_prefecture_candidates(value: str) -> list[str]:
    return payment_form_fields_service.jp_prefecture_candidates(
        value,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )


def _normalize_jp_prefecture_value(value: str) -> str:
    return payment_form_fields_service.normalize_jp_prefecture_value(
        value,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )


def _state_value_matches(expected: str, actual: str) -> bool:
    return payment_form_fields_service.state_value_matches(
        expected,
        actual,
        state_name_to_code=US_STATE_NAME_TO_CODE,
        state_code_to_name=US_STATE_CODE_TO_NAME,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )


def _card_value_matches(expected: str, actual: str, *, field: str) -> bool:
    return payment_form_fields_service.card_value_matches(
        expected,
        actual,
        field=field,
        normalize_card_expiry=_normalize_paypal_card_expiry,
    )


def _field_value_matches(expected: str, actual: str, *, field: str = "") -> bool:
    return payment_form_fields_service.field_value_matches(
        expected,
        actual,
        field=field,
        state_name_to_code=US_STATE_NAME_TO_CODE,
        state_code_to_name=US_STATE_CODE_TO_NAME,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
        normalize_card_expiry=_normalize_paypal_card_expiry,
        normalize_phone=_normalize_paypal_phone,
        phone_value_valid=_paypal_phone_value_valid,
    )


def _set_verified_locator_value(locator, value: str, *, field: str = "") -> bool:
    return payment_form_fields_service.set_verified_locator_value(
        locator,
        value,
        field=field,
        setters=(_dispatch_locator_value, _set_locator_value, _type_locator_value),
        read_value=_read_locator_value,
        matches=_field_value_matches,
    )


def _body_excerpt(api: ChatGPTTeamAPI, limit: int = 2000):
    return payment_checkout_browser_service.body_excerpt_with_frames(
        api,
        limit,
        frames=_iter_page_frames,
    )


def _emit_progress(on_progress, event: dict):
    if callable(on_progress):
        on_progress(event)


def _progress_event(stage: str, message: str = "", **kwargs):
    return paypal_task_payloads_service.paypal_progress_event(stage, message, **kwargs)


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
            lock = threading.RLock()
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
    if not _paypal_phone_value_valid(phone, country=str(signup_profile.get("country") or "")):
        return False, f"PayPal 注册手机号无效: {phone!r}"
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
        message = (
            kwargs.pop("message", "")
            or PAYPAL_AUTO_STAGE_MESSAGES.get(mapped_stage)
            or PAYPAL_AUTO_STAGE_MESSAGES.get(stage)
            or mapped_stage
        )
        _emit_progress(on_progress, _progress_event(mapped_stage, message, **kwargs))

    return _adapter


def _sync_relevant_payment_page(api: ChatGPTTeamAPI, *, prefer_paypal: bool = False):
    return payment_checkout_browser_service.sync_relevant_payment_page(
        api,
        prefer_primary=prefer_paypal,
        is_primary_url=_is_paypal_host,
        is_relevant_url=_is_checkout_host,
    )


def _normalize_paypal_country(value: str = "") -> str:
    return paypal_preflight_service.normalize_paypal_country(value)


def _normalize_paypal_lang(value: str = "", country: str = "US") -> str:
    return paypal_preflight_service.normalize_paypal_lang(value, country=country)


def _normalize_paypal_bind_task_runtime_options(
    *,
    manual_confirm: bool,
    paypal_mode: str,
    paypal_browser: str,
    paypal_fallback_browser: str,
    paypal_country: str,
    paypal_lang: str,
    proxy_url: str | None,
    proxy_bypass: str | None,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
) -> dict[str, Any]:
    return paypal_preflight_service.normalize_paypal_bind_task_runtime_options(
        manual_confirm=manual_confirm,
        paypal_mode=paypal_mode,
        paypal_browser=paypal_browser,
        paypal_fallback_browser=paypal_fallback_browser,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
    )


def _force_paypal_us_locale(api: ChatGPTTeamAPI, *, country: str = "US", lang: str = "en") -> bool:
    current_url = str(getattr(api.page, "url", "") or "")
    if not _is_paypal_host(current_url):
        return False
    next_url = paypal_preflight_service.paypal_locale_redirect_url(current_url, country=country, lang=lang)
    if not next_url:
        return False
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
    return payment_checkout_state_service.infer_paypal_stage(url, body_text)


def _fast_autofill_checkout_fields(api: ChatGPTTeamAPI, fields: dict[str, str]) -> list[str]:
    return payment_form_fields_service.fast_autofill_fields(
        _iter_page_frames(api),
        fields,
        fast_selectors=AUTOFILL_FAST_SELECTORS,
    )


def autofill_checkout_fields(api: ChatGPTTeamAPI, payload: dict | None, *, on_progress=None) -> dict:
    current_url = getattr(api.page, "url", "")

    def progress(filled: list[str], url: str) -> None:
        _emit_progress(
            on_progress,
            _progress_event(
                "paypal_autofill",
                f"已自动填写账单/联系字段: {', '.join(filled)}",
                autofill_fields=filled,
                url=url,
            ),
        )

    return payment_form_fields_service.autofill_checkout_fields(
        payload,
        current_url=current_url,
        selectors=AUTOFILL_SELECTORS,
        normalize_payload=normalize_autofill_payload,
        autofill_allowed=_autofill_allowed,
        suppress_autocomplete=lambda: _suppress_address_autocomplete_ui(api),
        dismiss_autocomplete=lambda locator=None: _dismiss_address_autocomplete(api, locator),
        fast_autofill=lambda fields: _fast_autofill_checkout_fields(api, fields),
        read_checkout_value=lambda key: _read_checkout_field_value(api, key),
        checkout_value_matches=_checkout_value_matches,
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        set_value=_set_locator_value,
        progress=progress,
    )


def _read_checkout_field_value(api: ChatGPTTeamAPI, key: str) -> str:
    return payment_form_fields_service.read_checkout_field_value(
        key=key,
        selectors=AUTOFILL_SELECTORS,
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        read_value=_read_locator_value,
    )


def _checkout_value_matches(key: str, expected: str, actual: str) -> bool:
    return payment_form_fields_service.checkout_value_matches(
        key,
        expected,
        actual,
        state_name_to_code=US_STATE_NAME_TO_CODE,
        state_code_to_name=US_STATE_CODE_TO_NAME,
        prefecture_name_to_ja=JP_PREFECTURE_NAME_TO_JA,
    )


def _fill_paypal_checkout_billing_form(
    api: ChatGPTTeamAPI,
    billing_payload: dict[str, str],
    session_id: str,
    screenshot_paths: list[str],
    *,
    on_progress=None,
) -> tuple[bool, str]:
    progress = _progress_adapter(on_progress)
    return payment_form_fields_service.fill_checkout_billing_form(
        billing_payload,
        suppress_autocomplete=lambda: _suppress_address_autocomplete_ui(api),
        autofill_checkout=lambda payload: autofill_checkout_fields(api, payload, on_progress=on_progress),
        read_checkout_value=lambda key: _read_checkout_field_value(api, key),
        checkout_value_matches=_checkout_value_matches,
        capture_failure=lambda: _capture_screenshot(
            api,
            session_id,
            "paypal-billing-address-failed",
            screenshot_paths,
        ),
        progress=progress,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
    )


def _extract_auth_session_context(email: str) -> dict[str, str]:
    return chatgpt_session_service.extract_auth_session_context(
        email,
        load_session=load_auth_session,
        auth_file_context=_load_chatgpt_auth_file_context(email),
    )


def _email_from_access_token(access_token: str) -> str:
    return chatgpt_session_service.email_from_access_token(access_token)


def _paypal_approve_checkout_http(
    http: Any,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    session_token: str = "",
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
    user_agent: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
) -> dict:
    if (
        access_token
        or session_token
        or cookie_header
        or account_id
        or device_id
        or user_agent
        or openai_sentinel_token
        or oai_client_version
        or oai_client_build_number
    ):
        _configure_chatgpt_http_session(
            http,
            access_token=access_token,
            session_token=session_token,
            cookie_header=cookie_header,
            account_id=account_id,
            device_id=device_id,
            user_agent=user_agent,
            openai_sentinel_token=openai_sentinel_token,
            oai_client_version=oai_client_version,
            oai_client_build_number=oai_client_build_number,
        )
    approve_path = "/backend-api/payments/checkout/approve"
    try:
        resolved_user_agent = str((getattr(http, "headers", {}) or {}).get("User-Agent") or "")
    except Exception:
        resolved_user_agent = ""
    headers = _chatgpt_checkout_headers(
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        cookie_header=cookie_header or _cookie_header_from_http_session(http),
        account_id=account_id,
        device_id=device_id,
        target_path=approve_path,
        openai_sentinel_token="",
    )
    sentinel_headers = _checkout_approval_sentinel_headers(
        cookie_header=headers.get("cookie", ""),
        user_agent=resolved_user_agent,
        checkout_url=f"https://chatgpt.com/checkout/{processor_entity}/{checkout_session_id}",
    )
    headers.update(sentinel_headers)
    headers.pop("openai-sentinel-token", None)
    if resolved_user_agent:
        headers["user-agent"] = resolved_user_agent
    try:
        http.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=30,
        )
    except Exception as exc:
        logger.info("[paypal_extract] sentinel ping before approve skipped: %s", exc)
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json={
            "checkout_session_id": checkout_session_id,
            "processor_entity": processor_entity,
        },
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        raise GoPayFlowError(
            f"ChatGPT approve 失败: HTTP {resp.status_code} {(resp.text or '')[:500]}",
            stage="chatgpt_approve",
        )
    payload = _response_json(resp, "paypal_chatgpt_approve")
    if payload.get("result") not in (None, "approved"):
        raise GoPayFlowError(f"ChatGPT approve 未通过: {payload}", stage="chatgpt_approve")
    return payload


def _wait_for_paypal_checkout_interactive(api: ChatGPTTeamAPI, *, timeout_seconds: int = 45) -> bool:
    return payment_checkout_browser_service.wait_paypal_checkout_interactive(
        api,
        paypal_selectors=PAYPAL_CHECKOUT_SELECTORS,
        submit_selectors=CHECKOUT_SUBMIT_SELECTORS,
        visible_locator=lambda selectors, timeout: _visible_locator_in_frames(api, selectors, timeout_ms=timeout),
        body_excerpt=_body_excerpt,
        timeout_seconds=timeout_seconds,
        logger=logger,
        url_summary=_safe_url_summary,
    )


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
    return payment_checkout_browser_service.click_first_visible(
        selectors,
        visible_locator=lambda candidates, timeout: _visible_locator_in_frames(api, candidates, timeout_ms=timeout),
        timeout_ms=timeout_ms,
    )


def _locator_is_checked(locator) -> bool:
    return payment_checkout_browser_service.locator_is_checked(locator)


def _is_paypal_option_selected(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.paypal_option_selected(
        api,
        state_selectors=PAYPAL_CHECKOUT_STATE_SELECTORS,
        attached_locator=lambda selectors, timeout: _attached_locator_in_frames(api, selectors, timeout_ms=timeout),
        locator_checked=_locator_is_checked,
        timeout_ms=300,
    )


def _click_paypal_checkout_control(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.click_paypal_checkout_control(
        api,
        checkout_selectors=PAYPAL_CHECKOUT_SELECTORS,
        state_selectors=PAYPAL_CHECKOUT_STATE_SELECTORS,
        click_first=lambda selectors, timeout: _click_first(api, selectors, timeout_ms=timeout),
        attached_locator=lambda selectors, timeout: _attached_locator_in_frames(api, selectors, timeout_ms=timeout),
        frames=_iter_page_frames,
    )


def _select_paypal_option(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    return payment_checkout_browser_service.select_paypal_option(
        api,
        paypal_host=_is_paypal_host,
        option_selected=_is_paypal_option_selected,
        click_control=_click_paypal_checkout_control,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


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
            return _build_result(
                "failed", failure_stage="submit_checkout", message="任务已取消", screenshot_paths=screenshot_paths
            )

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
    return payment_checkout_browser_service.inspect_paypal_page(
        api,
        paypal_host=_is_paypal_host,
        ensure_captcha_bypass=_ensure_paypal_hosted_captcha_bypass,
        body_excerpt=_body_excerpt,
        visible_locator=lambda selectors, timeout: _visible_locator_in_frames(api, selectors, timeout_ms=timeout),
        has_phone_rejected_prompt=_has_paypal_phone_rejected_prompt,
        has_otp_inputs=_has_paypal_otp_inputs,
        phone_rejected_text_hint=_paypal_phone_rejected_text_hint,
        card_rejected_text_hint=_paypal_card_rejected_text_hint,
        signup_registration_text_hint=_paypal_signup_registration_text_hint,
        signup_otp_text_hint=_paypal_signup_otp_text_hint,
        login_text_hint=_paypal_login_text_hint,
        passkey_text_hint=_paypal_passkey_text_hint,
        approve_text_hint=_paypal_approve_text_hint,
        email_selectors=PAYPAL_EMAIL_SELECTORS,
        password_selectors=PAYPAL_PASSWORD_SELECTORS,
        approve_selectors=PAYPAL_APPROVE_SELECTORS,
        prompt_selectors=PAYPAL_DISMISS_PROMPT_SELECTORS,
        create_account_selectors=PAYPAL_CREATE_ACCOUNT_SELECTORS,
        phone_selectors=PAYPAL_PHONE_SELECTORS,
        card_selectors=PAYPAL_CARD_NUMBER_SELECTORS,
    )


def _paypal_signup_registration_form_visible(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.paypal_signup_registration_form_visible(
        api,
        body_excerpt=_body_excerpt,
        text_visible=_paypal_signup_registration_form_text_visible,
        visible_locator=lambda selectors, timeout: _visible_locator_in_frames(api, selectors, timeout_ms=timeout),
        field_selector_groups=(
            PAYPAL_PHONE_SELECTORS,
            PAYPAL_CARD_NUMBER_SELECTORS,
            PAYPAL_CARD_EXPIRY_SELECTORS,
            PAYPAL_PASSWORD_SELECTORS,
            PAYPAL_BIRTH_DATE_SELECTORS,
        ),
    )


def _dismiss_paypal_prompts(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    return payment_checkout_browser_service.dismiss_paypal_prompts(
        api,
        prompt_selectors=PAYPAL_DISMISS_PROMPT_SELECTORS,
        click_first=lambda selectors, timeout: _click_first(api, selectors, timeout_ms=timeout),
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _click_paypal_phone_rejected_ok_in_frame(frame) -> bool:
    return payment_checkout_browser_service.click_paypal_phone_rejected_ok_in_frame(frame)


def _dismiss_paypal_phone_rejected_prompt(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.dismiss_paypal_phone_rejected_prompt(
        api,
        frames=_iter_page_frames,
        click_ok_in_frame=_click_paypal_phone_rejected_ok_in_frame,
        click_first=lambda selectors, timeout: _click_first(api, selectors, timeout_ms=timeout),
        has_prompt=_has_paypal_phone_rejected_prompt,
        prompt_selectors=PAYPAL_DISMISS_PROMPT_SELECTORS,
    )


def _has_paypal_phone_rejected_prompt(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.has_paypal_phone_rejected_prompt(
        api,
        rejected_selectors=PAYPAL_PHONE_REJECTED_SELECTORS,
        visible_locator=lambda selectors, timeout: _visible_locator_in_frames(api, selectors, timeout_ms=timeout),
        body_excerpt=_body_excerpt,
        text_hint=_paypal_phone_rejected_text_hint,
    )


def _set_first_visible_value(api: ChatGPTTeamAPI, selectors: list[str], value: str) -> bool:
    return payment_form_fields_service.set_first_visible_value(
        selectors=selectors,
        value=value,
        visible_locator=lambda field_selectors, timeout_ms: _visible_locator_in_frames(
            api,
            field_selectors,
            timeout_ms=timeout_ms,
        ),
        set_value=_set_locator_value,
    )


def _set_first_visible_value_with_locator(api: ChatGPTTeamAPI, selectors: list[str], value: str):
    return payment_form_fields_service.set_first_visible_value_with_locator(
        selectors=selectors,
        value=value,
        visible_locator=lambda field_selectors, timeout_ms: _visible_locator_in_frames(
            api,
            field_selectors,
            timeout_ms=timeout_ms,
        ),
        set_value=_set_locator_value,
    )


def _set_paypal_country(api: ChatGPTTeamAPI, country: str) -> bool:
    locator = _visible_locator_in_frames(api, PAYPAL_COUNTRY_SELECTORS, timeout_ms=1200)
    if not locator:
        return False
    country_labels = {
        "JP": ("Japan", "日本"),
        "US": ("United States", "United States of America"),
    }
    return payment_form_fields_service.select_country_locator(
        locator,
        country,
        normalize_country=_normalize_paypal_country,
        country_labels=country_labels,
    )


def _dismiss_paypal_cookie_banner(api: ChatGPTTeamAPI) -> bool:
    dismissed = _click_first(api, PAYPAL_COOKIE_BANNER_ACCEPT_SELECTORS, timeout_ms=700)
    for frame in _iter_page_frames(api):
        try:
            result = frame.evaluate(PAYPAL_COOKIE_BANNER_DISMISS_SCRIPT)
        except Exception:
            continue
        if result is True or (isinstance(result, dict) and result.get("dismissed")):
            dismissed = True
    if dismissed:
        try:
            api.page.wait_for_timeout(300)
        except Exception:
            time.sleep(0.3)
    return dismissed


def _press_escape_to_dismiss_browser_bubbles(api: ChatGPTTeamAPI) -> None:
    try:
        api.page.keyboard.press("Escape")
        api.page.wait_for_timeout(200)
    except Exception:
        time.sleep(0.2)


def _js_click_paypal_signup_submit(api: ChatGPTTeamAPI) -> bool:
    clicked = False
    for frame in _iter_page_frames(api):
        try:
            result = frame.evaluate(PAYPAL_SIGNUP_SUBMIT_CLICK_SCRIPT)
        except Exception:
            continue
        if result is True or (
            isinstance(result, dict) and (result.get("clicked") or result.get("skipped"))
        ):
            clicked = True
            break
    if clicked:
        try:
            api.page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
    return clicked


def _mark_paypal_signup_submit_clicked(api: ChatGPTTeamAPI) -> None:
    try:
        api._paypal_signup_submit_clicked_at = time.monotonic()
    except Exception:
        pass
    for frame in _iter_page_frames(api):
        try:
            frame.evaluate(PAYPAL_SIGNUP_SUBMIT_MARK_SCRIPT)
        except Exception:
            continue


def _click_paypal_signup_submit(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    try:
        last_clicked_at = float(getattr(api, "_paypal_signup_submit_clicked_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        last_clicked_at = 0.0
    if last_clicked_at and time.monotonic() - last_clicked_at < 15.0:
        return True

    _dismiss_paypal_cookie_banner(api)
    _dismiss_paypal_prompts(api, on_progress=on_progress)
    _press_escape_to_dismiss_browser_bubbles(api)
    _dismiss_paypal_cookie_banner(api)
    if _js_click_paypal_signup_submit(api):
        _mark_paypal_signup_submit_clicked(api)
        return True
    if _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=1500):
        _mark_paypal_signup_submit_clicked(api)
        return True
    return False


def _fill_paypal_signup_visible_form(api: ChatGPTTeamAPI, signup_profile: dict[str, str | bool]) -> dict[str, Any]:
    payload = payment_form_fields_service.build_signup_visible_form_payload(
        signup_profile,
        normalize_country=_normalize_paypal_country,
        default_birth_date=DEFAULT_PAYPAL_JP_BIRTH_DATE,
        default_native_first_name=DEFAULT_PAYPAL_JP_NATIVE_FIRST_NAME,
        default_native_last_name=DEFAULT_PAYPAL_JP_NATIVE_LAST_NAME,
    )
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
        if (field === 'country') return by((c) => c.tag === 'select' && /country|region|国\/地域/.test(c.direct));
        if (field === 'email') return by((c) => c.type === 'email' || /\bemail\b|メール/.test(c.direct));
        if (field === 'phone') return by((c) => c.tag !== 'select' && /phone number|mobile number|telephone|phone|電話番号|携帯電話|携帯/.test(c.direct) && !/phone type|電話のタイプ/.test(c.direct));
        if (field === 'card_number') return by((c) => /card number|cc-number|cardnumber|カード番号/.test(c.direct));
        if (field === 'card_expiry') return by((c) => /expiration|expiry|exp date|cc-exp|有効期限/.test(c.direct));
        if (field === 'card_cvv') return by((c) => /cvv|cvc|security code|cc-csc|セキュリティコード/.test(c.direct));
        if (field === 'password') return by((c) => c.type === 'password' || /create password|password|パスワード/.test(c.direct));
        if (field === 'first_name') return by((c) => /first name|given-name|firstname|(^|\s)名(\s|$)/.test(c.direct));
        if (field === 'last_name') return by((c) => /last name|family-name|lastname|(^|\s)姓(\s|$)/.test(c.direct));
        if (field === 'address1') return by((c) => /street address|address line 1|address-line1|address1|住所|番地/.test(c.direct));
        if (field === 'city') return by((c) => /\bcity\b|address-level2|市区町村|市区郡|市町村/.test(c.direct));
        if (field === 'state') return by((c) => /\bstate\b|address-level1|都道府県/.test(c.direct));
        if (field === 'zip') return by((c) => /zip code|postal code|postcode|postal-code|\bzip\b|郵便番号/.test(c.direct));
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
          .filter((c) => /(^|\s)(名|姓)(\s|$)|漢字|かな|カナ|名前/.test(c.direct))
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
          .filter((c) => /(^|\s)(名|姓)(\s|$)|漢字|かな|カナ|名前/.test(c.direct))
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
    if not _paypal_phone_value_valid(
        str(signup_profile.get("phone") or ""),
        country=str(signup_profile.get("country") or ""),
    ):
        return False, f"PayPal 注册手机号无效: {str(signup_profile.get('phone') or '')!r}"
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
    ok, error, field_locators = payment_form_fields_service.fill_signup_required_fields(
        required_fields,
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        set_verified_value=_set_verified_locator_value,
        read_value=_read_locator_value,
        optional_skip_fields=_OPTIONAL_SKIP_FIELDS,
        field_locators=field_locators,
        logger=logger,
        log_prefix="[paypal_signup]",
    )
    if not ok:
        return False, error

    _suppress_address_autocomplete_ui(api)
    address_fields = [
        ("address1", PAYPAL_BILLING_LINE1_SELECTORS, str(signup_profile.get("address1") or ""), "PayPal 账单地址"),
        ("city", PAYPAL_BILLING_CITY_SELECTORS, str(signup_profile.get("city") or ""), "PayPal 城市"),
        ("zip", PAYPAL_BILLING_POSTAL_SELECTORS, str(signup_profile.get("zip") or ""), "PayPal 邮编"),
        ("state", PAYPAL_BILLING_STATE_SELECTORS, str(signup_profile.get("state") or ""), "PayPal 州"),
    ]
    ok, error, field_locators = payment_form_fields_service.fill_signup_address_fields(
        address_fields,
        country=str(signup_profile.get("country") or "US"),
        suppress_autocomplete=lambda: _suppress_address_autocomplete_ui(api),
        dismiss_autocomplete=lambda locator=None: _dismiss_address_autocomplete(api, locator),
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        set_verified_value=_set_verified_locator_value,
        set_state_value=_set_paypal_state_locator_value,
        read_value=_read_locator_value,
        field_value_matches=_field_value_matches,
        set_value=_set_locator_value,
        field_locators=field_locators,
    )
    if not ok:
        return False, error

    ok, error = payment_form_fields_service.fill_signup_birth_date_if_needed(
        signup_profile,
        country=str(signup_profile.get("country") or ""),
        default_birth_date=DEFAULT_PAYPAL_JP_BIRTH_DATE,
        birth_date_selectors=PAYPAL_BIRTH_DATE_SELECTORS,
        normalize_country=_normalize_paypal_country,
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        set_value=_set_locator_value,
        read_value=_read_locator_value,
        logger=logger,
        log_prefix="[paypal_signup]",
    )
    if not ok:
        return False, error

    ok, error, _still_missing = payment_form_fields_service.validate_signup_dom_result(
        _fill_paypal_signup_visible_form(api, signup_profile),
        country=str(signup_profile.get("country") or ""),
        optional_skip_fields=_OPTIONAL_SKIP_FIELDS,
        normalize_country=_normalize_paypal_country,
        logger=logger,
        log_prefix="[paypal_bind_executor]",
    )
    if not ok:
        return False, error
    return True, ""


def _paypal_signup_visible_validation_error(api: ChatGPTTeamAPI) -> str:
    return payment_form_fields_service.paypal_signup_visible_validation_error(_body_excerpt(api, 12000))


def _paypal_signup_otp_text_hint(text: str, *, loose: bool = False) -> bool:
    return payment_form_fields_service.paypal_signup_otp_text_hint(text, loose=loose)


def _paypal_signup_otp_entry_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_signup_otp_entry_text_hint(text)


def _paypal_signup_registration_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_signup_registration_text_hint(text)


def _paypal_signup_registration_form_text_visible(text: str) -> bool:
    return payment_form_fields_service.paypal_signup_registration_form_text_visible(text)


def _paypal_login_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_login_text_hint(text)


def _paypal_passkey_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_passkey_text_hint(text)


def _paypal_approve_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_approve_text_hint(text)


def _paypal_phone_rejected_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_phone_rejected_text_hint(text, hints=PAYPAL_PHONE_REJECTED_HINTS)


def _paypal_card_rejected_text_hint(text: str) -> bool:
    return payment_form_fields_service.paypal_card_rejected_text_hint(text, hints=PAYPAL_CARD_REJECTED_HINTS)


def _fill_paypal_otp_inputs(api: ChatGPTTeamAPI, otp_code: str) -> bool:
    digits = re.sub(r"\D+", "", str(otp_code or ""))[:8]
    if len(digits) < 5:
        return False
    _dismiss_paypal_cookie_banner(api)
    script = """(code) => {
      const digits = String(code || '').replace(/\\D+/g, '').slice(0, 8).split('');
      if (digits.length < 5) return { filled: false, count: 0 };
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const pageText = String(document.body?.innerText || '').toLowerCase();
      const otpDialog = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]')).find((node) => {
        const text = String(node.innerText || '').toLowerCase();
        return isVisible(node) && (
          text.includes('enter your code') ||
          text.includes('6-digit code') ||
          text.includes('verification code') ||
          text.includes('security code') ||
          text.includes('コードを入力') ||
          text.includes('セキュリティコード') ||
          text.includes('確認コード') ||
          text.includes('認証コード')
        );
      });
      const root = otpDialog || document;
      const visibleInputs = Array.from(root.querySelectorAll('input, [role="textbox"], [contenteditable="true"]')).filter((node) => {
        return isVisible(node);
      });
      const candidates = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || node.getAttribute('inputmode') || '').toLowerCase();
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
          identity.includes('one-time-code') ||
          identity.includes('コード') ||
          identity.includes('認証') ||
          identity.includes('確認') ||
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
        const mode = String(node.inputMode || node.getAttribute('inputmode') || '').toLowerCase();
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
      const scrollTarget = otpDialog || orderedTargets[0]?.closest?.('form') || orderedTargets[0] || candidates[0] || null;
      try { scrollTarget?.scrollIntoView?.({ block: 'center', inline: 'nearest' }); } catch {}
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
                        continue
                except Exception:
                    pass
                try:
                    for index, box in enumerate(boxes[: len(digits)]):
                        api.page.mouse.click(float(box["x"]), float(box["y"]))
                        api.page.keyboard.type(digits[index], delay=30)
                    time.sleep(0.5)
                    continue
                except Exception:
                    pass
            try:
                locator = frame.locator(
                    '[role="dialog"] input, [aria-modal="true"] input, .modal input, [class*="modal" i] input, [role="dialog"] [role="textbox"], [aria-modal="true"] [role="textbox"]'
                ).first
                if locator.is_visible(timeout=250):
                    locator.click(timeout=1000)
                    locator.type(digits, delay=40, timeout=5000)
                    time.sleep(0.5)
                    continue
            except Exception:
                pass
        try:
            body_text = _body_excerpt(api, 2000)
        except Exception:
            body_text = ""
        if _paypal_signup_otp_entry_text_hint(body_text):
            try:
                viewport = api.page.viewport_size or {"width": 1280, "height": 800}
            except Exception:
                viewport = {"width": 1280, "height": 800}
            try:
                # The PayPal OTP modal can be partially covered by the bottom cookie banner.
                # Click above the bottom overlay zone when no concrete input box was detected.
                api.page.mouse.click(float(viewport["width"]) * 0.39, float(viewport["height"]) * 0.58)
                api.page.keyboard.type(digits, delay=50)
                time.sleep(0.3)
                continue
            except Exception:
                pass
        time.sleep(0.5)
    return False


def _click_paypal_otp_submit(api: ChatGPTTeamAPI) -> bool:
    script = """() => {
      const isVisible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const dialogs = Array.from(document.querySelectorAll(
        '[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]'
      )).filter(isVisible);
      const dialog = dialogs.find((node) => {
        const text = String(node.innerText || '').toLowerCase();
        return (
          text.includes('enter your code') ||
          text.includes('6-digit code') ||
          text.includes('verification code') ||
          text.includes('security code') ||
          text.includes('コードを入力') ||
          text.includes('セキュリティコード') ||
          text.includes('確認コード') ||
          text.includes('認証コード')
        );
      });
      if (!dialog) return false;
      const controls = Array.from(dialog.querySelectorAll(
        'button, input[type="submit"], input[type="button"], [role="button"]'
      )).filter((node) => {
        if (!isVisible(node) || node.disabled) return false;
        const text = String(node.innerText || node.value || node.getAttribute('aria-label') || '').trim();
        return !/resend|send again|close|cancel|再送|閉じる|キャンセル|取消|关闭|關閉/i.test(text);
      });
      const preferred = controls.find((node) => {
        const text = String(node.innerText || node.value || node.getAttribute('aria-label') || '').trim();
        return /continue|next|submit|confirm|verify|done|続行|次へ|送信|確認|完了|继续|提交|确认|驗證/i.test(text);
      });
      const target = preferred || (controls.length === 1 ? controls[0] : null);
      if (!target) return false;
      target.click();
      return true;
    }"""
    for frame in _iter_page_frames(api):
        try:
            if frame.evaluate(script):
                return True
        except Exception:
            continue
    return False


def _has_paypal_otp_inputs(api: ChatGPTTeamAPI) -> bool:
    script = """() => {
      const visibleInputs = Array.from(document.querySelectorAll('input')).filter((node) => {
        return Boolean(node.offsetParent || node.getClientRects?.().length);
      });
      const oneCharInputs = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || node.getAttribute('inputmode') || '').toLowerCase();
        const maxLength = Number(node.maxLength || 0);
        return maxLength === 1 && (mode === 'numeric' || type === 'tel' || type === 'text' || !type);
      });
      if (oneCharInputs.length >= 4 && oneCharInputs.length <= 8) return true;
      const candidates = visibleInputs.filter((node) => {
        const type = String(node.type || '').toLowerCase();
        const mode = String(node.inputMode || node.getAttribute('inputmode') || '').toLowerCase();
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
          identity.includes('code') ||
          identity.includes('コード') ||
          identity.includes('認証') ||
          identity.includes('確認') ||
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
    return payment_checkout_browser_service.click_paypal_create_account(
        api,
        create_account_selectors=PAYPAL_CREATE_ACCOUNT_SELECTORS,
        click_first=lambda selectors, timeout: _click_first(api, selectors, timeout_ms=timeout),
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _is_paypal_pay_entry_url(url: str) -> bool:
    return payment_checkout_state_service.is_paypal_pay_entry_url(url)


def _paypal_signup_email_step_advanced(api: ChatGPTTeamAPI, before_url: str) -> bool:
    """Return True once PayPal advances from the /pay email gate."""
    return payment_checkout_browser_service.paypal_signup_email_step_advanced(
        api,
        before_url,
        sync_payment_page=_sync_relevant_payment_page,
        is_pay_entry_url=_is_paypal_pay_entry_url,
        inspect_page=_inspect_paypal_page,
    )


def _wait_paypal_signup_email_step_advanced(
    api: ChatGPTTeamAPI, before_url: str, *, timeout_seconds: float = 8.0
) -> bool:
    return payment_checkout_browser_service.wait_paypal_signup_email_step_advanced(
        api,
        before_url,
        step_advanced=_paypal_signup_email_step_advanced,
        timeout_seconds=timeout_seconds,
    )


def _js_click_paypal_signup_email_submit(api: ChatGPTTeamAPI) -> bool:
    return payment_checkout_browser_service.js_click_paypal_signup_email_submit(
        api,
        frames=_iter_page_frames,
        logger=logger,
    )


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
    return payment_checkout_browser_service.js_recover_paypal_email_spinner(api, email)


def _inspect_paypal_email_gate(api: ChatGPTTeamAPI) -> dict[str, Any]:
    return payment_checkout_browser_service.inspect_paypal_email_gate(api)


def _submit_paypal_signup_email_step(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    on_progress=None,
) -> tuple[bool, str]:
    return payment_checkout_browser_service.submit_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        submit_selectors=PAYPAL_SIGNUP_EMAIL_SUBMIT_SELECTORS,
        set_locator_value=_set_locator_value,
        click_first=lambda selectors, timeout: _click_first(api, selectors, timeout_ms=timeout),
        wait_step_advanced=_wait_paypal_signup_email_step_advanced,
        js_click_submit=_js_click_paypal_signup_email_submit,
        inspect_gate=_inspect_paypal_email_gate,
        body_excerpt=_body_excerpt,
        progress_event=_progress_event,
        on_progress=on_progress,
        logger=logger,
        url_summary=_safe_url_summary,
        compact_log_text=_compact_log_text,
    )


def _replace_paypal_signup_phone(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    return payment_form_fields_service.replace_paypal_signup_phone(
        api,
        signup_profile=signup_profile,
        phone_selectors=PAYPAL_PHONE_SELECTORS,
        phone_value_valid=_paypal_phone_value_valid,
        set_first_visible_value_with_locator=lambda selectors, value: _set_first_visible_value_with_locator(
            api,
            selectors,
            value,
        ),
        set_verified_value=_set_verified_locator_value,
        read_value=_read_locator_value,
        on_progress=on_progress,
        progress_event=_progress_event,
    )


def _verify_paypal_signup_required_values(
    api: ChatGPTTeamAPI, signup_profile: dict[str, str | bool]
) -> tuple[bool, str]:
    return payment_form_fields_service.verify_paypal_signup_required_values(
        signup_profile,
        phone_selectors=PAYPAL_PHONE_SELECTORS,
        card_number_selectors=PAYPAL_CARD_NUMBER_SELECTORS,
        card_expiry_selectors=PAYPAL_CARD_EXPIRY_SELECTORS,
        card_cvv_selectors=PAYPAL_CARD_CVV_SELECTORS,
        password_selectors=PAYPAL_PASSWORD_SELECTORS,
        first_name_selectors=PAYPAL_FIRST_NAME_SELECTORS,
        last_name_selectors=PAYPAL_LAST_NAME_SELECTORS,
        address1_selectors=PAYPAL_BILLING_LINE1_SELECTORS,
        city_selectors=PAYPAL_BILLING_CITY_SELECTORS,
        postal_selectors=PAYPAL_BILLING_POSTAL_SELECTORS,
        state_selectors=PAYPAL_BILLING_STATE_SELECTORS,
        phone_value_valid=_paypal_phone_value_valid,
        visible_locator=lambda selectors, timeout_ms: _visible_locator_in_frames(api, selectors, timeout_ms=timeout_ms),
        read_value=_read_locator_value,
        field_value_matches=_field_value_matches,
    )


def _replace_paypal_signup_card(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    on_progress=None,
) -> tuple[bool, str]:
    return payment_form_fields_service.replace_paypal_signup_card(
        api,
        signup_profile=signup_profile,
        card_number_selectors=PAYPAL_CARD_NUMBER_SELECTORS,
        card_expiry_selectors=PAYPAL_CARD_EXPIRY_SELECTORS,
        card_cvv_selectors=PAYPAL_CARD_CVV_SELECTORS,
        generate_card_number=_generate_paypal_card_number,
        generate_card_expiry=_generate_paypal_card_expiry,
        generate_card_cvv=_generate_paypal_card_cvv,
        set_first_visible_value_with_locator=lambda selectors, value: _set_first_visible_value_with_locator(
            api,
            selectors,
            value,
        ),
        set_verified_value=_set_verified_locator_value,
        read_value=_read_locator_value,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _retry_paypal_signup_after_card_rejected(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    card_retry_count: int,
    current_url: str,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_form_fields_service.retry_paypal_signup_after_card_rejected(
        api,
        signup_profile=signup_profile,
        state=state,
        card_retry_count=card_retry_count,
        current_url=current_url,
        replace_signup_card=_replace_paypal_signup_card,
        ensure_phone_lock=_ensure_paypal_signup_phone_lock,
        release_phone_lock=_release_paypal_signup_phone_lock,
        verify_required_values=_verify_paypal_signup_required_values,
        click_submit=lambda api: _click_paypal_signup_submit(api, on_progress=on_progress),
        progress_event=_progress_event,
        on_progress=on_progress,
        now=time.time,
        sleep=time.sleep,
    )


def _retry_paypal_signup_after_phone_rejected(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    phone_key: str,
    submitted_phone_keys: set[str],
    current_url: str,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_form_fields_service.retry_paypal_signup_after_phone_rejected(
        api,
        signup_profile=signup_profile,
        state=state,
        phone_key=phone_key,
        submitted_phone_keys=submitted_phone_keys,
        current_url=current_url,
        ensure_phone_lock=_ensure_paypal_signup_phone_lock,
        replace_signup_phone=_replace_paypal_signup_phone,
        release_phone_lock=_release_paypal_signup_phone_lock,
        verify_required_values=_verify_paypal_signup_required_values,
        click_submit=lambda api: _click_paypal_signup_submit(api, on_progress=on_progress),
        progress_event=_progress_event,
        on_progress=on_progress,
        now=time.time,
        sleep=time.sleep,
    )


def _wait_paypal_signup_registration_dom(api: ChatGPTTeamAPI) -> None:
    try:
        api.page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass


def _paypal_signup_loading_state(api: ChatGPTTeamAPI) -> bool:
    script = """() => {
      const visible = (node) => Boolean(node && (node.offsetParent || node.getClientRects?.().length));
      const selectors = [
        '[role="progressbar"]',
        '[aria-busy="true"]',
        '[data-testid*="spinner" i]',
        '[data-testid*="loading" i]',
        '[class*="spinner" i]',
        '[class*="loading" i]',
        '[class*="progress" i]'
      ];
      return selectors.some((selector) => Array.from(document.querySelectorAll(selector)).some(visible));
    }"""
    for frame in _iter_page_frames(api):
        try:
            if frame.evaluate(script):
                return True
        except Exception:
            continue
    return False


def _submit_paypal_signup_registration_form(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    phone_key: str,
    submitted_phone_keys: set[str],
    current_url: str,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_form_fields_service.submit_paypal_signup_registration_form(
        api,
        signup_profile=signup_profile,
        state=state,
        phone_key=phone_key,
        submitted_phone_keys=submitted_phone_keys,
        current_url=current_url,
        wait_dom_loaded=_wait_paypal_signup_registration_dom,
        ensure_phone_lock=_ensure_paypal_signup_phone_lock,
        fill_signup_form=_fill_paypal_signup_form,
        release_phone_lock=_release_paypal_signup_phone_lock,
        verify_required_values=_verify_paypal_signup_required_values,
        click_submit=lambda api: _click_paypal_signup_submit(api, on_progress=on_progress),
        progress_event=_progress_event,
        is_loading_state=_paypal_signup_loading_state,
        on_progress=on_progress,
        logger=logger,
        now=time.time,
        sleep=time.sleep,
    )


def _click_paypal_signup_otp_resend(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    return payment_checkout_browser_service.click_paypal_signup_otp_resend(
        api,
        frames=_iter_page_frames,
        click_first=lambda selectors, timeout_ms: _click_first(api, selectors, timeout_ms=timeout_ms),
        progress_event=_progress_event,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _poll_paypal_signup_otp(
    *,
    api: ChatGPTTeamAPI,
    signup_profile: dict[str, str | bool],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
) -> str:
    return sms_otp_service.poll_paypal_signup_otp(
        signup_profile,
        timeout_seconds=timeout_seconds,
        otp_poll_timeout_seconds=PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS,
        resend_after_seconds=PAYPAL_SIGNUP_OTP_RESEND_AFTER_SECONDS,
        max_resend_attempts=PAYPAL_SIGNUP_OTP_MAX_RESEND_ATTEMPTS,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        progress_event=_progress_event,
        url_summary=_safe_url_summary,
        progress_adapter=_progress_adapter,
        poll_otp_from_sms_url_fn=_poll_otp_from_sms_url,
        click_resend=lambda: _click_paypal_signup_otp_resend(api, on_progress=on_progress),
    )


def _submit_paypal_login_step(
    api: ChatGPTTeamAPI,
    *,
    credentials: dict[str, str],
    state: dict[str, Any],
    on_progress=None,
):
    return payment_checkout_browser_service.submit_paypal_login_step(
        api,
        credentials=credentials,
        state=state,
        next_selectors=PAYPAL_NEXT_SELECTORS,
        set_locator_value=_set_locator_value,
        click_first=lambda selectors, timeout_ms: _click_first(api, selectors, timeout_ms=timeout_ms),
        progress_event=_progress_event,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _click_paypal_approve(api: ChatGPTTeamAPI, *, on_progress=None) -> bool:
    return payment_checkout_browser_service.click_paypal_approve(
        api,
        approve_selectors=PAYPAL_APPROVE_SELECTORS,
        click_first=lambda selectors, timeout_ms: _click_first(api, selectors, timeout_ms=timeout_ms),
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _wait_for_paypal_subscription_return(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int = PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
    is_cancelled=None,
    on_progress=None,
):
    return payment_checkout_browser_service.wait_for_paypal_subscription_return(
        api,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        settle_seconds=PAYPAL_APPROVE_RETURN_SETTLE_SECONDS,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        progress_event=_progress_event,
        capture_screenshot=_capture_screenshot,
        build_result=_build_result,
        sync_relevant_payment_page=_sync_relevant_payment_page,
        is_return_url=_is_chatgpt_or_openai_return_url,
        is_paypal_host=_is_paypal_host,
        classify_paypal_checkout_state=classify_paypal_checkout_state,
        body_excerpt=_body_excerpt,
        time_fn=time.time,
        sleep=time.sleep,
    )


def _handle_paypal_left_host(
    *,
    current_url: str,
    otp_phone_lock_key: str,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_left_host(
        current_url=current_url,
        otp_phone_lock_key=otp_phone_lock_key,
        paypal_host=_is_paypal_host,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _paypal_left_host_values(left_host_result: dict[str, Any]) -> str:
    return payment_checkout_browser_service.paypal_left_host_values(left_host_result)


def _prepare_paypal_authorize_flow_context(
    *,
    paypal_mode: str,
    credentials: dict[str, str],
    signup_profile: dict[str, str | bool] | None,
    phone_accounts: list[dict] | None,
    timeout_seconds: int,
    paypal_country: str,
    paypal_lang: str,
) -> dict[str, Any]:
    context = payment_checkout_browser_service.prepare_paypal_authorize_flow_context(
        paypal_mode=paypal_mode,
        credentials=credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        timeout_seconds=timeout_seconds,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        normalize_paypal_country=_normalize_paypal_country,
        normalize_paypal_lang=_normalize_paypal_lang,
        signup_profiles_for_phone_pool=_paypal_signup_profiles_for_phone_pool,
        now=time.time,
    )
    if paypal_mode == "create_account":
        signup_profiles = [dict(item or {}) for item in list(context.get("signup_profiles") or [])]
        for profile in signup_profiles:
            sms_url = str(profile.get("sms_url") or "").strip()
            if not sms_url:
                continue
            try:
                existing_code = str(sms_otp_service.fetch_sms_code(sms_url) or "").strip()
            except Exception as exc:
                logger.info("[paypal_signup] existing OTP snapshot skipped: %s", exc)
                existing_code = ""
            if existing_code:
                ignored = {str(item or "").strip() for item in (profile.get("_ignored_otps") or [])}
                ignored.add(existing_code)
                profile["_ignored_otps"] = sorted(item for item in ignored if item)
        if signup_profiles:
            context["signup_profiles"] = signup_profiles
            index = int(context.get("signup_profile_index") or 0)
            context["active_signup_profile"] = signup_profiles[max(0, min(index, len(signup_profiles) - 1))]
    return context


def _handle_paypal_authorize_cancelled(
    *,
    is_cancelled,
    otp_phone_lock_key: str,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_authorize_cancelled(
        is_cancelled=is_cancelled,
        otp_phone_lock_key=otp_phone_lock_key,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        on_progress=on_progress,
    )


def _paypal_authorize_cancelled_result_fields(
    cancelled_result: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    return payment_checkout_browser_service.paypal_authorize_cancelled_result_fields(cancelled_result)


def _handle_paypal_phone_rejected_rotation(
    api: ChatGPTTeamAPI,
    *,
    paypal_mode: str,
    classified: dict[str, Any] | None,
    signup_profile_index: int,
    signup_profiles: list[dict[str, Any]],
    active_signup_profile: dict[str, Any],
    current_url: str,
    otp_phone_lock_key: str,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_phone_rejected_rotation(
        api,
        paypal_mode=paypal_mode,
        classified=classified,
        signup_profile_index=signup_profile_index,
        signup_profiles=signup_profiles,
        active_signup_profile=active_signup_profile,
        current_url=current_url,
        otp_phone_lock_key=otp_phone_lock_key,
        dismiss_phone_rejected_prompt=_dismiss_paypal_phone_rejected_prompt,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        progress_event=_progress_event,
        url_summary=_safe_url_summary,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _paypal_authorize_datadome_failed_result_fields(
    result: dict[str, Any],
    *,
    default_stage: str = "paypal_datadome_blocked",
    default_message: str,
) -> tuple[str, str, str]:
    return payment_checkout_browser_service.paypal_authorize_datadome_failed_result_fields(
        result,
        default_stage=default_stage,
        default_message=default_message,
    )


def _paypal_phone_rejected_rotation_values(
    rotation_result: dict[str, Any],
    *,
    otp_phone_lock_key: str,
    signup_profile_index: int,
    active_signup_profile: dict[str, Any],
    signup_form_submitted: bool,
    signup_submitted_at: float,
    phone_only_retry: bool,
    card_retry_count: int,
) -> tuple[str, int, dict[str, Any], bool, float, bool, int]:
    return payment_checkout_browser_service.paypal_phone_rejected_rotation_values(
        rotation_result,
        otp_phone_lock_key=otp_phone_lock_key,
        signup_profile_index=signup_profile_index,
        active_signup_profile=active_signup_profile,
        signup_form_submitted=signup_form_submitted,
        signup_submitted_at=signup_submitted_at,
        phone_only_retry=phone_only_retry,
        card_retry_count=card_retry_count,
    )


def _paypal_authorize_classified_return_values(
    classification_result: dict[str, Any],
    fallback_classified: dict[str, Any] | None,
    *,
    default_screenshot_label: str,
) -> tuple[str, str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_authorize_classified_return_values(
        classification_result,
        fallback_classified,
        default_screenshot_label=default_screenshot_label,
    )


def _paypal_authorize_classification_refresh_count(
    classification_result: dict[str, Any],
    *,
    ddc_blocked_refresh_count: int,
) -> int:
    return payment_checkout_browser_service.paypal_authorize_classification_refresh_count(
        classification_result,
        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
    )


def _handle_paypal_authorize_failed_classification(
    api: ChatGPTTeamAPI,
    *,
    classified: dict[str, Any] | None,
    paypal_mode: str,
    active_signup_profile: dict[str, Any],
    signup_profile_index: int,
    signup_profiles: list[dict[str, Any]],
    current_url: str,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
    max_ddc_blocked_refreshes: int,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_authorize_failed_classification(
        api,
        classified=classified,
        paypal_mode=paypal_mode,
        active_signup_profile=active_signup_profile,
        signup_profile_index=signup_profile_index,
        signup_profiles=signup_profiles,
        current_url=current_url,
        otp_phone_lock_key=otp_phone_lock_key,
        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
        max_ddc_blocked_refreshes=max_ddc_blocked_refreshes,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        progress_event=_progress_event,
        logger=logger,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _handle_paypal_authorize_review_classification(
    api: ChatGPTTeamAPI,
    *,
    classified: dict[str, Any] | None,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
    max_ddc_blocked_refreshes: int,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_authorize_review_classification(
        api,
        classified=classified,
        otp_phone_lock_key=otp_phone_lock_key,
        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
        max_ddc_blocked_refreshes=max_ddc_blocked_refreshes,
        is_ddc_blocked_page=_is_ddc_blocked_page,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        progress_event=_progress_event,
        logger=logger,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _handle_paypal_authorize_ddc_blocked_page(
    api: ChatGPTTeamAPI,
    *,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
    max_ddc_blocked_refreshes: int,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_authorize_ddc_blocked_page(
        api,
        otp_phone_lock_key=otp_phone_lock_key,
        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
        max_ddc_blocked_refreshes=max_ddc_blocked_refreshes,
        is_ddc_blocked_page=_is_ddc_blocked_page,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        progress_event=_progress_event,
        logger=logger,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _paypal_authorize_ddc_blocked_page_values(
    blocked_page_result: dict[str, Any],
    *,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
) -> tuple[str, int]:
    return payment_checkout_browser_service.paypal_authorize_ddc_blocked_page_values(
        blocked_page_result,
        otp_phone_lock_key=otp_phone_lock_key,
        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
    )


def _handle_paypal_authorize_ddc_challenge(
    api: ChatGPTTeamAPI,
    *,
    otp_phone_lock_key: str,
    last_ddc_check_at: float,
    ddc_iframe_check_interval: float = 15.0,
    ddc_pass_timeout_seconds: int = 50,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_authorize_ddc_challenge(
        api,
        otp_phone_lock_key=otp_phone_lock_key,
        last_ddc_check_at=last_ddc_check_at,
        ddc_iframe_check_interval=ddc_iframe_check_interval,
        ddc_pass_timeout_seconds=ddc_pass_timeout_seconds,
        ddc_slider_visible=_ddc_slider_visible,
        has_ddc_iframe=_has_ddc_iframe,
        wait_ddc_pass=_wait_ddc_pass,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        on_progress=on_progress,
        now=time.time,
    )


def _paypal_authorize_ddc_challenge_values(
    ddc_challenge_result: dict[str, Any],
    *,
    otp_phone_lock_key: str,
    last_ddc_check_at: float,
) -> tuple[str, float]:
    return payment_checkout_browser_service.paypal_authorize_ddc_challenge_values(
        ddc_challenge_result,
        otp_phone_lock_key=otp_phone_lock_key,
        last_ddc_check_at=last_ddc_check_at,
    )


def _handle_paypal_result_datadome_check(
    api: ChatGPTTeamAPI,
    *,
    last_ddc_check_at: float,
    ddc_iframe_check_interval: float = 15.0,
    ddc_pass_timeout_seconds: int = 50,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_result_datadome_check(
        api,
        last_ddc_check_at=last_ddc_check_at,
        ddc_iframe_check_interval=ddc_iframe_check_interval,
        ddc_pass_timeout_seconds=ddc_pass_timeout_seconds,
        is_ddc_blocked_page=_is_ddc_blocked_page,
        ddc_slider_visible=_ddc_slider_visible,
        has_ddc_iframe=_has_ddc_iframe,
        wait_ddc_pass=_wait_ddc_pass,
        logger=logger,
        on_progress=on_progress,
        now=time.time,
        sleep=time.sleep,
    )


def _paypal_result_datadome_values(
    datadome_result: dict[str, Any],
    *,
    last_ddc_check_at: float,
) -> float:
    return payment_checkout_browser_service.paypal_result_datadome_values(
        datadome_result,
        last_ddc_check_at=last_ddc_check_at,
    )


def _should_continue_after_paypal_result_datadome(datadome_result: dict[str, Any]) -> bool:
    return payment_checkout_browser_service.should_continue_after_paypal_result_datadome(datadome_result)


def _paypal_result_datadome_transition(
    datadome_result: dict[str, Any],
    *,
    last_ddc_check_at: float,
) -> tuple[float, bool]:
    return payment_checkout_browser_service.paypal_result_datadome_transition(
        datadome_result,
        last_ddc_check_at=last_ddc_check_at,
    )


def _should_check_paypal_result_datadome(current_url: str) -> bool:
    return payment_checkout_browser_service.should_check_paypal_result_datadome(
        current_url,
        is_paypal_host=_is_paypal_host,
    )


def _paypal_result_browser_classification(current_url: str, body_text: str) -> dict[str, Any] | None:
    return payment_checkout_browser_service.paypal_result_browser_classification(
        current_url,
        body_text,
        classify_checkout_state=classify_paypal_checkout_state,
    )


def _paypal_result_browser_classified_values(current_url: str, body_text: str) -> tuple[str, dict[str, Any]] | None:
    return payment_checkout_browser_service.paypal_result_browser_classified_values(
        current_url,
        body_text,
        classify_checkout_state=classify_paypal_checkout_state,
    )


def _paypal_result_classified_return_values(classified_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_result_classified_return_values(classified_result)


def _attach_paypal_result_screenshot_paths(
    classified_result: dict[str, Any],
    screenshot_paths: list[str],
) -> dict[str, Any]:
    return payment_checkout_browser_service.attach_paypal_result_screenshot_paths(classified_result, screenshot_paths)


def _capture_and_attach_paypal_result_screenshot_paths(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_label: str,
    classified_result: dict[str, Any],
    screenshot_paths: list[str],
) -> dict[str, Any]:
    _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
    return _attach_paypal_result_screenshot_paths(classified_result, screenshot_paths)


def _paypal_result_cancelled_result_fields(result: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_result_cancelled_result_fields(result)


def _paypal_result_timeout_result_fields(result: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_result_timeout_result_fields(result)


def _paypal_result_wait_deadline(*, now: float, timeout_seconds: int) -> float:
    return payment_checkout_browser_service.paypal_result_wait_deadline(
        now=now,
        timeout_seconds=timeout_seconds,
    )


def _should_continue_paypal_result_wait(*, now: float, deadline: float) -> bool:
    return payment_checkout_browser_service.should_continue_paypal_result_wait(
        now=now,
        deadline=deadline,
    )


def _should_cancel_paypal_result_wait(is_cancelled) -> bool:
    return payment_checkout_browser_service.should_cancel_paypal_result_wait(is_cancelled)


def _paypal_result_wait_initial_state() -> tuple[str, float, float, float]:
    return payment_checkout_browser_service.paypal_result_wait_initial_state()


def _paypal_result_wait_sleep_seconds() -> float:
    return payment_checkout_browser_service.paypal_result_wait_sleep_seconds()


def _paypal_result_autofilled_url_keys() -> set[str]:
    return payment_checkout_browser_service.paypal_result_autofilled_url_keys()


def _paypal_result_stripe_state_http_session(proxy_url: str | None) -> Any:
    return payment_checkout_browser_service.paypal_result_stripe_state_http_session(
        proxy_url,
        new_http_session=_new_http_session,
    )


def _paypal_result_page_snapshot(api: ChatGPTTeamAPI) -> tuple[str, str]:
    return payment_checkout_browser_service.paypal_result_page_snapshot(
        api,
        body_excerpt=_body_excerpt,
    )


def _paypal_result_sync_prefer_paypal() -> bool:
    return payment_checkout_browser_service.paypal_result_sync_prefer_paypal()


def _paypal_result_autofill_url_key(url: str) -> str:
    return payment_checkout_browser_service.paypal_result_autofill_url_key(url)


def _should_autofill_paypal_result_checkout(
    current_url: str,
    autofill_payload: dict[str, Any] | None,
    *,
    autofill_enabled: bool = True,
) -> bool:
    return payment_checkout_browser_service.should_autofill_paypal_result_checkout(
        current_url,
        autofill_payload,
        autofill_enabled=autofill_enabled,
        is_checkout_host=_is_checkout_host,
        autofill_allowed=_autofill_allowed,
    )


def _should_run_paypal_result_autofill(
    *,
    should_autofill_checkout: bool,
    autofill_key: str,
    autofilled_url_keys: set[str],
) -> bool:
    return payment_checkout_browser_service.should_run_paypal_result_autofill(
        should_autofill_checkout=should_autofill_checkout,
        autofill_key=autofill_key,
        autofilled_url_keys=autofilled_url_keys,
    )


def _paypal_result_autofill_transition(
    current_url: str,
    autofill_payload: dict[str, Any] | None,
    *,
    autofilled_url_keys: set[str],
    autofill_enabled: bool = True,
) -> tuple[bool, str]:
    return payment_checkout_browser_service.paypal_result_autofill_transition(
        current_url,
        autofill_payload,
        autofilled_url_keys=autofilled_url_keys,
        autofill_enabled=autofill_enabled,
        is_checkout_host=_is_checkout_host,
        autofill_allowed=_autofill_allowed,
    )


def _record_paypal_result_autofill_key(
    autofilled_url_keys: set[str],
    autofill_key: str,
) -> set[str]:
    return payment_checkout_browser_service.record_paypal_result_autofill_key(autofilled_url_keys, autofill_key)


def _paypal_result_stripe_progress_event_fields(
    stripe_classified: dict[str, Any],
    *,
    checkout_url: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_result_stripe_progress_event_fields(
        stripe_classified,
        checkout_url=checkout_url,
        current_url=current_url,
    )


def _paypal_result_stripe_classified_values(
    stripe_classified: dict[str, Any],
    *,
    checkout_url: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any], str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_result_stripe_classified_values(
        stripe_classified,
        checkout_url=checkout_url,
        current_url=current_url,
    )


def _should_poll_paypal_result_stripe_state(
    *,
    checkout_url: str,
    now: float,
    last_poll_at: float,
    poll_interval_seconds: float = PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS,
) -> bool:
    return payment_checkout_browser_service.should_poll_paypal_result_stripe_state(
        checkout_url=checkout_url,
        now=now,
        last_poll_at=last_poll_at,
        poll_interval_seconds=poll_interval_seconds,
    )


def _paypal_result_stripe_poll_transition(
    *,
    checkout_url: str,
    now: float,
    last_poll_at: float,
    poll_interval_seconds: float = PAYPAL_STRIPE_STATE_POLL_INTERVAL_SECONDS,
) -> tuple[bool, float]:
    return payment_checkout_browser_service.paypal_result_stripe_poll_transition(
        checkout_url=checkout_url,
        now=now,
        last_poll_at=last_poll_at,
        poll_interval_seconds=poll_interval_seconds,
    )


def _should_emit_paypal_result_stage_progress(*, stage: str, last_stage: str) -> bool:
    return payment_checkout_browser_service.should_emit_paypal_result_stage_progress(
        stage=stage,
        last_stage=last_stage,
    )


def _paypal_result_stage_values(current_url: str, body_text: str) -> tuple[str, str]:
    return payment_checkout_browser_service.paypal_result_stage_values(
        current_url,
        body_text,
        infer_stage=infer_paypal_stage,
    )


def _paypal_result_stage_progress_transition(*, stage: str, last_stage: str) -> tuple[bool, str]:
    return payment_checkout_browser_service.paypal_result_stage_progress_transition(
        stage=stage,
        last_stage=last_stage,
    )


def _paypal_result_stage_progress_event_fields(
    *,
    stage: str,
    message: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_result_stage_progress_event_fields(
        stage=stage,
        message=message,
        current_url=current_url,
    )


def _should_log_paypal_result_wait(
    *,
    now: float,
    last_log_at: float,
    log_interval_seconds: float = 60.0,
) -> bool:
    return payment_checkout_browser_service.should_log_paypal_result_wait(
        now=now,
        last_log_at=last_log_at,
        log_interval_seconds=log_interval_seconds,
    )


def _paypal_result_wait_log_transition(
    *,
    now: float,
    last_log_at: float,
    log_interval_seconds: float = 60.0,
) -> tuple[bool, float]:
    return payment_checkout_browser_service.paypal_result_wait_log_transition(
        now=now,
        last_log_at=last_log_at,
        log_interval_seconds=log_interval_seconds,
    )


def _paypal_result_wait_log_values(
    *,
    deadline: float,
    now: float,
    current_url: str,
) -> tuple[int, str]:
    return payment_checkout_browser_service.paypal_result_wait_log_values(
        deadline=deadline,
        now=now,
        current_url=current_url,
    )


def _handle_paypal_browser_fallback_ddc_wait(
    page,
    *,
    timeout_seconds: int = 50,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_browser_fallback_ddc_wait(
        page,
        wait_ddc_pass=_wait_ddc_pass,
        timeout_seconds=timeout_seconds,
        on_progress=on_progress,
    )


def _handle_paypal_protocol_browser_fallback_context(
    protocol_result: dict[str, Any],
    *,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_protocol_browser_fallback_context(
        protocol_result,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        extract_ba_token=_paypal_protocol_extract_ba_token,
        create_account_entry_url=_paypal_create_account_entry_url,
        safe_url_summary=_safe_url_summary,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _preserve_paypal_roxybrowser_on_failure(
    api: ChatGPTTeamAPI,
    result: dict[str, Any],
    *,
    fallback_use_roxybrowser: bool,
) -> dict[str, Any]:
    return payment_checkout_browser_service.preserve_paypal_roxybrowser_on_failure(
        api,
        result,
        fallback_use_roxybrowser=fallback_use_roxybrowser,
        keepalive_seconds=PAYPAL_ROXYBROWSER_FAILURE_KEEPALIVE_SECONDS,
    )


def _handle_paypal_pre_extracted_checkout_without_ba(
    pre_extracted: dict[str, Any] | None,
    *,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_pre_extracted_checkout_without_ba(
        pre_extracted,
        safe_url_summary=_safe_url_summary,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _handle_paypal_proxy_open_checkout_failure(
    prepare_result: dict[str, Any] | None,
    *,
    proxy_url: str | None,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_proxy_open_checkout_failure(
        prepare_result,
        proxy_url=proxy_url,
        is_tunnel_connection_error=_is_tunnel_connection_error,
        safe_url_summary=_safe_url_summary,
        progress_event=_progress_event,
        logger=logger,
        on_progress=on_progress,
    )


def _handle_paypal_manual_pre_wait_autofill(
    api: ChatGPTTeamAPI,
    *,
    autofill_payload: dict[str, Any] | None,
    autofill_enabled: bool = True,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_manual_pre_wait_autofill(
        api,
        autofill_payload=autofill_payload,
        autofill_enabled=autofill_enabled,
        autofill_checkout_fields=autofill_checkout_fields,
        on_progress=on_progress,
    )


def _handle_paypal_open_checkout_cancelled(*, is_cancelled) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_open_checkout_cancelled(is_cancelled=is_cancelled)


def _launch_paypal_checkout_browser(
    api: ChatGPTTeamAPI,
    *,
    proxy_url: str | None,
    proxy_bypass: str | None,
    use_fallback_browser: bool,
    paypal_country: str,
    paypal_lang: str,
    use_camoufox: bool,
    use_roxybrowser: bool,
    fallback_use_camoufox: bool,
    fallback_use_roxybrowser: bool,
    browser_fallback_enabled: bool = False,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    on_progress=None,
) -> None:
    payment_checkout_browser_service.launch_paypal_checkout_browser(
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        use_fallback_browser=use_fallback_browser,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        use_camoufox=use_camoufox,
        use_roxybrowser=use_roxybrowser,
        fallback_use_camoufox=fallback_use_camoufox,
        fallback_use_roxybrowser=fallback_use_roxybrowser,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        launch_browser=api._launch_browser,
        on_progress=on_progress,
    )


def _handle_paypal_checkout_context_dispatch(
    api: ChatGPTTeamAPI,
    *,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    session_id: str,
    screenshot_paths: list[str],
    is_cancelled=None,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_checkout_context_dispatch(
        api,
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        is_cancelled=is_cancelled,
        handle_open_checkout_cancelled=_handle_paypal_open_checkout_cancelled,
        build_result=_build_result,
        prepare_chatgpt_checkout_context=_prepare_chatgpt_checkout_context,
        extract_auth_session_context=_extract_auth_session_context,
        handle_proxy_open_checkout_failure=_handle_paypal_proxy_open_checkout_failure,
        on_progress=on_progress,
    )


def _handle_paypal_manual_result_wait(
    api: ChatGPTTeamAPI,
    *,
    checkout_url: str,
    proxy_url: str | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    autofill_enabled: bool = False,
    autofill_payload: dict[str, Any] | None = None,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_manual_result_wait(
        api,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        manual_pre_wait_autofill=_handle_paypal_manual_pre_wait_autofill,
        wait_for_paypal_result=_wait_for_paypal_result,
        on_progress=on_progress,
    )


def _handle_paypal_post_checkout_flow_dispatch(
    api: ChatGPTTeamAPI,
    *,
    auto_mode: bool,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_email: str,
    paypal_password: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
    phone_accounts: list[dict[str, Any]] | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    autofill_enabled: bool = False,
    autofill_payload: dict[str, Any] | None = None,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_post_checkout_flow_dispatch(
        api,
        auto_mode=auto_mode,
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        phone_accounts=phone_accounts,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        handle_auto_flow_dispatch=_handle_paypal_auto_flow_dispatch,
        handle_manual_result_wait=_handle_paypal_manual_result_wait,
        paypal_result_timeout_seconds=_paypal_result_timeout_seconds,
        on_progress=on_progress,
    )


def _handle_paypal_unexpected_error(
    api: ChatGPTTeamAPI,
    exc: Exception,
    *,
    session_id: str,
    screenshot_paths: list[str],
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_unexpected_error(
        api,
        exc,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        logger=logger,
        capture_screenshot=_capture_screenshot,
        build_result=_build_result,
    )


def _stop_paypal_api_safely(api: ChatGPTTeamAPI) -> None:
    payment_checkout_browser_service.stop_paypal_api_safely(api)


def _prepare_paypal_auto_flow_payloads(
    *,
    autofill_payload: dict[str, Any] | None,
    autofill_enabled: bool,
    paypal_country: str,
    proxy_url: str | None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.prepare_paypal_auto_flow_payloads(
        autofill_payload=autofill_payload,
        autofill_enabled=autofill_enabled,
        paypal_country=paypal_country,
        proxy_url=proxy_url,
        resolve_checkout_billing_payload=_resolve_checkout_billing_payload,
        prepare_signup_billing_payload=_prepare_paypal_signup_billing_payload,
    )


def _prepare_paypal_auto_flow_identity(
    *,
    paypal_email: str,
    paypal_password: str,
    signup_billing_payload: dict[str, Any],
    paypal_country: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
) -> dict[str, Any]:
    return payment_checkout_browser_service.prepare_paypal_auto_flow_identity(
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        signup_billing_payload=signup_billing_payload,
        paypal_country=paypal_country,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        normalize_paypal_credentials=_normalize_paypal_credentials,
        build_paypal_signup_profile=_build_paypal_signup_profile,
    )


def _handle_paypal_auto_flow_dispatch(
    api: ChatGPTTeamAPI,
    *,
    auto_mode: bool,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_email: str,
    paypal_password: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
    phone_accounts: list[dict[str, Any]] | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    autofill_enabled: bool = False,
    autofill_payload: dict[str, Any] | None = None,
    on_progress=None,
    browser_fallback_enabled: bool = True,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_auto_flow_dispatch(
        api,
        auto_mode=auto_mode,
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        phone_accounts=phone_accounts,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        prepare_auto_flow_payloads=_prepare_paypal_auto_flow_payloads,
        prepare_auto_flow_identity=_prepare_paypal_auto_flow_identity,
        run_paypal_auto_flow=_run_paypal_auto_flow,
        on_progress=on_progress,
    )


def _handle_paypal_auto_flow_checkout_handoff(
    api: ChatGPTTeamAPI,
    *,
    current_url: str,
    email: str,
    billing_payload: dict[str, Any],
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled,
    progress,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_auto_flow_checkout_handoff(
        api,
        current_url=current_url,
        email=email,
        billing_payload=billing_payload,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        progress=progress,
        is_checkout_host=_is_checkout_host,
        page_url=lambda: getattr(api.page, "url", ""),
        browser_checkout_nonzero_amount_hint=_browser_checkout_nonzero_amount_hint,
        capture_screenshot=_capture_screenshot,
        build_result=_build_result,
        select_paypal_option=_select_paypal_option,
        autofill_allowed=_autofill_allowed,
        has_complete_billing_payload=_has_complete_billing_payload,
        emit_progress=_emit_progress,
        progress_event=_progress_event,
        fill_paypal_checkout_billing_form=_fill_paypal_checkout_billing_form,
        accept_checkout_terms_on_page=_accept_checkout_terms_on_page,
        submit_checkout_to_paypal=_submit_checkout_to_paypal,
        on_progress=on_progress,
    )


def _handle_paypal_protocol_flow_dispatch(
    *,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_email: str,
    paypal_password: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
    phone_accounts: list[dict[str, Any]] | None,
    timeout_seconds: int,
    is_cancelled=None,
    autofill_enabled: bool = False,
    autofill_payload: dict[str, Any] | None = None,
    pre_extracted: dict[str, Any] | None = None,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_protocol_flow_dispatch(
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        phone_accounts=phone_accounts,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        pre_extracted=pre_extracted,
        prepare_auto_flow_payloads=_prepare_paypal_auto_flow_payloads,
        build_paypal_signup_profile=_build_paypal_signup_profile,
        run_paypal_protocol_flow=_run_paypal_protocol_flow,
        on_progress=on_progress,
    )


def _handle_paypal_protocol_browser_fallback_dispatch(
    api: ChatGPTTeamAPI,
    *,
    fallback_context: dict[str, Any],
    fallback_approve_url: str,
    fallback_ba_token: str,
    proxy_url: str | None,
    proxy_bypass: str | None,
    fallback_use_camoufox: bool,
    fallback_use_roxybrowser: bool,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_email: str,
    paypal_password: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
    phone_accounts: list[dict[str, Any]] | None,
    signup_billing_payload: dict[str, Any],
    checkout_url: str,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_protocol_browser_fallback_dispatch(
        api,
        fallback_context=fallback_context,
        fallback_approve_url=fallback_approve_url,
        fallback_ba_token=fallback_ba_token,
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        fallback_use_camoufox=fallback_use_camoufox,
        fallback_use_roxybrowser=fallback_use_roxybrowser,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        phone_accounts=phone_accounts,
        signup_billing_payload=signup_billing_payload,
        checkout_url=checkout_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        launch_browser=api._launch_browser,
        emit_progress=_emit_progress,
        progress_event=_progress_event,
        goto_paypal_page_with_retries=_goto_paypal_page_with_retries,
        handle_browser_fallback_ddc_wait=_handle_paypal_browser_fallback_ddc_wait,
        build_result=_build_result,
        preserve_roxybrowser_on_failure=lambda result: _preserve_paypal_roxybrowser_on_failure(
            api,
            result,
            fallback_use_roxybrowser=fallback_use_roxybrowser,
        ),
        ensure_captcha_bypass=_ensure_paypal_hosted_captcha_bypass,
        normalize_paypal_credentials=_normalize_paypal_credentials,
        build_paypal_signup_profile=_build_paypal_signup_profile,
        run_paypal_authorize_flow=_run_paypal_authorize_flow,
        paypal_authorize_timeout_seconds=_paypal_authorize_timeout_seconds,
        wait_for_paypal_result=_wait_for_paypal_result,
        paypal_result_timeout_seconds=_paypal_result_timeout_seconds,
        on_progress=on_progress,
    )


def _handle_paypal_protocol_mode_dispatch(
    api: ChatGPTTeamAPI,
    *,
    protocol_mode: bool,
    pre_extracted: dict[str, Any] | None,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    proxy_bypass: str | None,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    paypal_email: str,
    paypal_password: str,
    sms_url: str,
    otp_channel: str,
    paypal_card_number: str,
    paypal_card_expiry: str,
    paypal_card_cvv: str,
    phone_accounts: list[dict[str, Any]] | None,
    timeout_seconds: int,
    session_id: str,
    screenshot_paths: list[str],
    fallback_use_camoufox: bool,
    fallback_use_roxybrowser: bool,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    is_cancelled=None,
    autofill_enabled: bool = False,
    autofill_payload: dict[str, Any] | None = None,
    on_progress=None,
    browser_fallback_enabled: bool = True,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_protocol_mode_dispatch(
        api,
        protocol_mode=protocol_mode,
        pre_extracted=pre_extracted,
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
        phone_accounts=phone_accounts,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        fallback_use_camoufox=fallback_use_camoufox,
        fallback_use_roxybrowser=fallback_use_roxybrowser,
        browser_fallback_enabled=browser_fallback_enabled,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        handle_pre_extracted_checkout_without_ba=_handle_paypal_pre_extracted_checkout_without_ba,
        build_result=_build_result,
        prepare_auto_flow_payloads=_prepare_paypal_auto_flow_payloads,
        handle_protocol_flow_dispatch=_handle_paypal_protocol_flow_dispatch,
        paypal_protocol_needs_browser_fallback=_paypal_protocol_needs_browser_fallback,
        handle_protocol_browser_fallback_context=_handle_paypal_protocol_browser_fallback_context,
        handle_protocol_browser_fallback_dispatch=_handle_paypal_protocol_browser_fallback_dispatch,
        on_progress=on_progress,
    )


def _handle_paypal_signup_stop_before_otp_authorize_result(state: dict[str, Any]) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_stop_before_otp_authorize_result(state)


def _paypal_signup_stop_before_otp_result_fields(
    stop_before_otp_result: dict[str, Any],
) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_signup_stop_before_otp_result_fields(stop_before_otp_result)


def _handle_paypal_signup_flow_failure_authorize_result(
    *,
    ok: bool,
    error: str,
    otp_phone_lock_key: str,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_flow_failure_authorize_result(
        ok=ok,
        error=error,
        otp_phone_lock_key=otp_phone_lock_key,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        on_progress=on_progress,
    )


def _paypal_signup_flow_failure_result_fields(
    signup_failure_result: dict[str, Any],
    *,
    fallback_error: str,
) -> tuple[str, str, str, str, str]:
    return payment_checkout_browser_service.paypal_signup_flow_failure_result_fields(
        signup_failure_result,
        fallback_error=fallback_error,
    )


def _handle_paypal_signup_login_redirect_authorize_result(
    login_redirect_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_login_redirect_authorize_result(login_redirect_result)


def _paypal_signup_login_redirect_continue_values(
    login_redirect_action: dict[str, Any],
) -> tuple[int, bool, float, bool, float]:
    return payment_checkout_browser_service.paypal_signup_login_redirect_continue_values(login_redirect_action)


def _paypal_signup_login_redirect_failed_result_fields(
    login_redirect_action: dict[str, Any],
) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_signup_login_redirect_failed_result_fields(login_redirect_action)


def _handle_paypal_signup_stuck_recover_authorize_result(
    stuck_recover_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_stuck_recover_authorize_result(stuck_recover_result)


def _paypal_signup_stuck_recover_failed_result_fields(
    stuck_recover_action: dict[str, Any],
) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_signup_stuck_recover_failed_result_fields(stuck_recover_action)


def _paypal_signup_stuck_recover_continue_values(
    stuck_recover_action: dict[str, Any],
) -> tuple[bool, float]:
    return payment_checkout_browser_service.paypal_signup_stuck_recover_continue_values(stuck_recover_action)


def _handle_paypal_login_step_failure_authorize_result(*, ok: bool, error: str) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_login_step_failure_authorize_result(ok=ok, error=error)


def _paypal_login_step_failure_result_fields(
    login_failure_result: dict[str, Any],
    *,
    fallback_error: str,
) -> tuple[str, str, str, str]:
    return payment_checkout_browser_service.paypal_login_step_failure_result_fields(
        login_failure_result,
        fallback_error=fallback_error,
    )


def _handle_paypal_authorize_timeout(
    *,
    otp_phone_lock_key: str,
    on_progress=None,
) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_authorize_timeout(
        otp_phone_lock_key=otp_phone_lock_key,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        on_progress=on_progress,
    )


def _paypal_authorize_timeout_result_fields(timeout_result: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return payment_checkout_browser_service.paypal_authorize_timeout_result_fields(timeout_result)


def _handle_paypal_signup_visible_state_wait(
    state: dict[str, Any],
    *,
    sleep_seconds: float = 1.5,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_visible_state_wait(
        state,
        sleep_seconds=sleep_seconds,
        sleep=time.sleep,
    )


def _handle_paypal_authorize_idle_wait(*, sleep_seconds: float = 1.0) -> dict[str, Any]:
    return payment_checkout_browser_service.handle_paypal_authorize_idle_wait(
        sleep_seconds=sleep_seconds,
        sleep=time.sleep,
    )


def _handle_paypal_approve_ready(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    otp_phone_lock_key: str,
    session_id: str,
    screenshot_paths: list[str],
    is_cancelled=None,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_approve_ready(
        api,
        state=state,
        otp_phone_lock_key=otp_phone_lock_key,
        click_approve=_click_paypal_approve,
        release_otp_phone_lock=_release_paypal_otp_phone_lock,
        wait_for_return=lambda api, on_progress=None: _wait_for_paypal_subscription_return(
            api,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=PAYPAL_APPROVE_RETURN_TIMEOUT_SECONDS,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        ),
        on_progress=on_progress,
    )


def _paypal_approve_return_values(approve_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return payment_checkout_browser_service.paypal_approve_return_values(approve_result)


def _maybe_enter_paypal_signup_from_login(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    signup_submitted: bool,
    signup_email_submitted: bool,
    paypal_country: str,
    paypal_lang: str,
    paypal_ba_token: str = "",
    on_progress=None,
) -> tuple[bool, str, bool] | None:
    return payment_checkout_browser_service.maybe_enter_paypal_signup_from_login(
        api,
        state=state,
        signup_submitted=signup_submitted,
        signup_email_submitted=signup_email_submitted,
        ba_token=paypal_ba_token,
        country=paypal_country,
        lang=paypal_lang,
        click_create_account=lambda api: _click_paypal_create_account(api, on_progress=on_progress),
        goto_create_account_entry=lambda api, **kwargs: _goto_paypal_create_account_entry(
            api,
            **kwargs,
            on_progress=on_progress,
        ),
        sleep=time.sleep,
    )


def _handle_paypal_signup_needs_login_redirect(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    signup_login_redirect_count: int,
    paypal_ba_token: str,
    paypal_country: str,
    paypal_lang: str,
    on_progress=None,
    sleep_after_redirect_seconds: float = 0.0,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.handle_paypal_signup_needs_login_redirect(
        api,
        state=state,
        signup_login_redirect_count=signup_login_redirect_count,
        max_redirects=3,
        ba_token=paypal_ba_token,
        country=paypal_country,
        lang=paypal_lang,
        goto_create_account_entry=_goto_paypal_create_account_entry,
        on_progress=on_progress,
        sleep_after_redirect_seconds=sleep_after_redirect_seconds,
        sleep=time.sleep,
    )


def _maybe_dismiss_paypal_passkey_prompt(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    on_progress=None,
) -> bool:
    return payment_checkout_browser_service.maybe_dismiss_paypal_passkey_prompt(
        api,
        state=state,
        dismiss_prompts=_dismiss_paypal_prompts,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _inspect_and_merge_paypal_state(
    api: ChatGPTTeamAPI,
    *,
    previous_state: dict[str, Any],
    paypal_ba_token: str,
) -> dict[str, Any]:
    return payment_checkout_browser_service.merge_paypal_inspected_state(
        previous_state,
        _inspect_paypal_page(api),
        ba_token=paypal_ba_token,
    )


def _maybe_mark_paypal_signup_registration_ready(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    signup_submitted: bool,
) -> bool:
    return payment_checkout_browser_service.maybe_mark_paypal_signup_registration_ready(
        api,
        state=state,
        signup_submitted=signup_submitted,
        registration_form_visible=_paypal_signup_registration_form_visible,
    )


def _maybe_click_paypal_signup_create_account_ready(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    on_progress=None,
) -> tuple[bool, str, bool] | None:
    return payment_checkout_browser_service.maybe_click_paypal_signup_create_account_ready(
        api,
        state=state,
        click_create_account=lambda api: _click_paypal_create_account(api, on_progress=on_progress),
        sleep=time.sleep,
    )


def _seed_paypal_signup_authorize_state(
    state: dict[str, Any],
    *,
    signup_email_submitted: bool,
    signup_email_submitted_at: float,
    signup_form_submitted: bool,
    signup_submitted_at: float,
    submitted_phone_keys: set[str],
    phone_only_retry: bool,
    card_retry_count: int,
    otp_phone_lock_key: str,
) -> dict[str, Any]:
    return payment_checkout_browser_service.seed_paypal_signup_authorize_state(
        state,
        signup_email_submitted=signup_email_submitted,
        signup_email_submitted_at=signup_email_submitted_at,
        signup_form_submitted=signup_form_submitted,
        signup_submitted_at=signup_submitted_at,
        submitted_phone_keys=submitted_phone_keys,
        phone_only_retry=phone_only_retry,
        card_retry_count=card_retry_count,
        otp_phone_lock_key=otp_phone_lock_key,
    )


def _sync_paypal_signup_authorize_state(
    state: dict[str, Any],
    *,
    signup_email_submitted: bool,
    signup_email_submitted_at: float,
    signup_form_submitted: bool,
    signup_submitted_at: float,
    card_retry_count: int,
) -> dict[str, Any]:
    return payment_checkout_browser_service.sync_paypal_signup_authorize_state(
        state,
        signup_email_submitted=signup_email_submitted,
        signup_email_submitted_at=signup_email_submitted_at,
        signup_form_submitted=signup_form_submitted,
        signup_submitted_at=signup_submitted_at,
        card_retry_count=card_retry_count,
        now=time.time,
    )


def _paypal_signup_authorize_state_values(
    signup_state: dict[str, Any],
) -> tuple[bool, float, bool, float, bool, int, str]:
    return payment_checkout_browser_service.paypal_signup_authorize_state_values(signup_state)


def _handle_paypal_signup_submitted_phase(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    card_retry_count: int,
    current_url: str,
    is_cancelled=None,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_checkout_browser_service.handle_paypal_signup_submitted_phase(
        api,
        signup_profile=signup_profile,
        state=state,
        card_retry_count=card_retry_count,
        current_url=current_url,
        is_cancelled=is_cancelled,
        visible_validation_error=_paypal_signup_visible_validation_error,
        release_phone_lock=_release_paypal_signup_phone_lock,
        retry_card_rejected=_retry_paypal_signup_after_card_rejected,
        stop_before_signup_otp_enabled=_paypal_stop_before_signup_otp_enabled,
        body_excerpt=_body_excerpt,
        has_otp_inputs=_has_paypal_otp_inputs,
        signup_otp_text_hint=_paypal_signup_otp_text_hint,
        stop_before_otp=_stop_before_paypal_signup_otp,
        maybe_wait_for_otp=_maybe_wait_for_paypal_signup_otp,
        submit_otp=_submit_paypal_signup_otp,
        on_progress=on_progress,
        sleep=time.sleep,
    )


def _paypal_signup_email_step_state(
    state: dict[str, Any],
    *,
    signup_email_submitted: bool,
) -> dict[str, Any]:
    return payment_checkout_browser_service.paypal_signup_email_step_state(
        state,
        signup_email_submitted=signup_email_submitted,
        wait_timeout_seconds=PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS,
        now=time.time,
    )


def _recover_paypal_signup_email_step(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    submitted_at: float,
    first_submitted_at: float,
    on_progress=None,
) -> tuple[bool, str, bool] | None:
    return payment_checkout_browser_service.recover_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        submitted_at=submitted_at,
        first_submitted_at=first_submitted_at,
        stuck_recover_delay_seconds=PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS,
        recover_email_spinner=_js_recover_paypal_email_spinner,
        progress_event=_progress_event,
        on_progress=on_progress,
        logger=logger,
        max_js_before_reload=1,
        max_reload_cycles=3,
        now=time.time,
        sleep=time.sleep,
    )


def _continue_paypal_signup_email_step(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    current_url: str,
    signup_email_submitted: bool,
    is_blank_after_email: bool,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_checkout_browser_service.continue_paypal_signup_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        current_url=current_url,
        signup_email_submitted=signup_email_submitted,
        is_blank_after_email=is_blank_after_email,
        submit_email_step=_submit_paypal_signup_email_step,
        progress_event=_progress_event,
        on_progress=on_progress,
        now=time.time,
        sleep=time.sleep,
    )


def _recover_paypal_signup_unhandled_email_stuck(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    signup_email_submitted: bool,
    signup_email_submitted_at: float,
    current_url: str,
    on_progress=None,
) -> dict[str, Any] | None:
    return payment_checkout_browser_service.recover_paypal_signup_unhandled_email_stuck(
        api,
        signup_profile=signup_profile,
        state=state,
        signup_email_submitted=signup_email_submitted,
        signup_email_submitted_at=signup_email_submitted_at,
        current_url=current_url,
        wait_timeout_seconds=PAYPAL_SIGNUP_EMAIL_STEP_WAIT_TIMEOUT_SECONDS,
        stuck_recover_delay_seconds=PAYPAL_SIGNUP_EMAIL_STUCK_RECOVER_DELAY_SECONDS,
        recover_email_spinner=_js_recover_paypal_email_spinner,
        progress_event=_progress_event,
        on_progress=on_progress,
        logger=logger,
        url_summary=_safe_url_summary,
        max_js_before_reload=1,
        max_reload_cycles=3,
        now=time.time,
        sleep=time.sleep,
    )


def _sync_paypal_signup_phone_submission_state(
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    *,
    signup_submitted: bool,
) -> tuple[bool, str, set[str], bool]:
    return payment_form_fields_service.sync_paypal_signup_phone_submission_state(
        signup_profile,
        state,
        signup_submitted=signup_submitted,
        normalize_phone=_normalize_paypal_phone,
    )


def _stop_before_paypal_signup_otp(
    *,
    state: dict[str, Any],
    signup_profile: dict[str, str | bool],
    current_url: str,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_checkout_browser_service.stop_before_paypal_signup_otp(
        state=state,
        signup_profile=signup_profile,
        current_url=current_url,
        progress_event=_progress_event,
        on_progress=on_progress,
    )


def _maybe_wait_for_paypal_signup_otp(
    api: ChatGPTTeamAPI,
    *,
    state: dict[str, Any],
    signup_profile: dict[str, str | bool],
    current_url: str,
    on_progress=None,
) -> tuple[bool, str, bool] | None:
    return payment_checkout_browser_service.maybe_wait_for_paypal_signup_otp(
        api,
        state=state,
        signup_profile=signup_profile,
        current_url=current_url,
        otp_wait_timeout_seconds=PAYPAL_SIGNUP_OTP_WAIT_TIMEOUT_SECONDS,
        body_excerpt=_body_excerpt,
        has_otp_inputs=_has_paypal_otp_inputs,
        signup_otp_text_hint=_paypal_signup_otp_text_hint,
        click_create_submit=lambda api: _click_first(api, PAYPAL_CREATE_SUBMIT_SELECTORS, timeout_ms=3000),
        progress_event=_progress_event,
        on_progress=on_progress,
        logger=logger,
        now=time.time,
        sleep=time.sleep,
    )


def _submit_paypal_signup_otp(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    current_url: str,
    is_cancelled=None,
    on_progress=None,
) -> tuple[bool, str, bool]:
    return payment_checkout_browser_service.submit_paypal_signup_otp(
        api,
        signup_profile=signup_profile,
        state=state,
        current_url=current_url,
        otp_poll_timeout_seconds=PAYPAL_SIGNUP_OTP_POLL_TIMEOUT_SECONDS,
        is_cancelled=is_cancelled,
        poll_signup_otp=_poll_paypal_signup_otp,
        fill_otp_inputs=_fill_paypal_otp_inputs,
        click_next=_click_paypal_otp_submit,
        release_phone_lock=_release_paypal_signup_phone_lock,
        progress_event=_progress_event,
        on_progress=on_progress,
        otp_cancelled_exception=GoPayOTPCancelled,
        sleep=time.sleep,
    )


def _run_paypal_signup_flow(
    api: ChatGPTTeamAPI,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    paypal_country: str = "US",
    paypal_lang: str = "en",
    paypal_ba_token: str = "",
    on_progress=None,
    is_cancelled=None,
) -> tuple[bool, str, bool]:
    current_url = getattr(api.page, "url", "")
    signup_submitted = bool(state.get("signup_submitted"))
    signup_email_submitted = bool(state.get("signup_email_submitted"))
    phone_only_retry = bool(state.get("phone_only_retry"))
    card_retry_count = int(state.get("card_retry_count") or 0)
    signup_submitted, phone_key, submitted_phone_keys, _phone_already_submitted = (
        _sync_paypal_signup_phone_submission_state(
            signup_profile,
            state,
            signup_submitted=signup_submitted,
        )
    )

    login_entry_result = _maybe_enter_paypal_signup_from_login(
        api,
        state=state,
        signup_submitted=signup_submitted,
        signup_email_submitted=signup_email_submitted,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_ba_token=paypal_ba_token,
        on_progress=on_progress,
    )
    if login_entry_result is not None:
        return login_entry_result

    _maybe_mark_paypal_signup_registration_ready(
        api,
        state=state,
        signup_submitted=signup_submitted,
    )

    if signup_submitted:
        return _handle_paypal_signup_submitted_phase(
            api,
            signup_profile=signup_profile,
            state=state,
            card_retry_count=card_retry_count,
            current_url=current_url,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )

    if phone_only_retry and (state.get("registration_ready") or state.get("registration_text_hint")):
        return _retry_paypal_signup_after_phone_rejected(
            api,
            signup_profile=signup_profile,
            state=state,
            phone_key=phone_key,
            submitted_phone_keys=submitted_phone_keys,
            current_url=current_url,
            on_progress=on_progress,
        )

    create_account_result = _maybe_click_paypal_signup_create_account_ready(
        api,
        state=state,
        on_progress=on_progress,
    )
    if create_account_result is not None:
        return create_account_result

    email_step_state = _paypal_signup_email_step_state(
        state,
        signup_email_submitted=signup_email_submitted,
    )
    _is_email_step = bool(email_step_state["is_email_step"])
    _is_blank_after_email = bool(email_step_state["is_blank_after_email"])
    if _is_email_step or _is_blank_after_email:
        if signup_email_submitted:
            timeout_result = email_step_state.get("timeout_result")
            if timeout_result is not None:
                return timeout_result
            submitted_at = float(email_step_state["submitted_at"])
            first_submitted_at = float(email_step_state["first_submitted_at"])

            # ── SPA 卡住恢复策略 ──
            # Camoufox 下 PayPal SPA 提交邮箱后可能出现内部状态死锁：
            #   - 没有 spinner DOM 元素（spinners_removed=0）
            #   - JS 注入重新提交表单无效（SPA 忽略）
            # 策略：先做 1 次 JS 快速尝试（~8s），若无效立即 reload
            # + 完整重置所有状态让流程从头走（email 输入→提交→等待表单）。
            # 允许最多 3 次 reload 周期（_email_reload_cycle_count）。
            recover_result = _recover_paypal_signup_email_step(
                api,
                signup_profile=signup_profile,
                state=state,
                submitted_at=submitted_at,
                first_submitted_at=first_submitted_at,
                on_progress=on_progress,
            )
            if recover_result is not None:
                return recover_result

        return _continue_paypal_signup_email_step(
            api,
            signup_profile=signup_profile,
            state=state,
            current_url=current_url,
            signup_email_submitted=signup_email_submitted,
            is_blank_after_email=_is_blank_after_email,
            on_progress=on_progress,
        )

    if state.get("registration_ready") or state.get("registration_text_hint"):
        return _submit_paypal_signup_registration_form(
            api,
            signup_profile=signup_profile,
            state=state,
            phone_key=phone_key,
            submitted_phone_keys=submitted_phone_keys,
            current_url=current_url,
            on_progress=on_progress,
        )

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
    paypal_ba_token: str = "",
    is_cancelled=None,
    on_progress=None,
    phone_accounts: list[dict] | None = None,
):
    context = _prepare_paypal_authorize_flow_context(
        paypal_mode=paypal_mode,
        credentials=credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        timeout_seconds=timeout_seconds,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
    )
    deadline = float(context["deadline"])
    paypal_country = str(context["paypal_country"])
    paypal_lang = str(context["paypal_lang"])
    effective_credentials = dict(context["effective_credentials"])
    signup_profiles = list(context["signup_profiles"])
    signup_profile_index = int(context["signup_profile_index"])
    active_signup_profile = context["active_signup_profile"]
    signup_email_submitted = bool(context["signup_email_submitted"])
    signup_email_submitted_at = float(context["signup_email_submitted_at"])
    signup_form_submitted = bool(context["signup_form_submitted"])
    signup_submitted_at = float(context["signup_submitted_at"])
    phone_only_retry = bool(context["phone_only_retry"])
    card_retry_count = int(context["card_retry_count"])
    submitted_phone_keys: set[str] = set(context["submitted_phone_keys"])
    otp_phone_lock_key = str(context["otp_phone_lock_key"])
    last_ddc_check_at = float(context["last_ddc_check_at"])
    ddc_blocked_refresh_count = int(context["ddc_blocked_refresh_count"])
    signup_login_redirect_count = int(context["signup_login_redirect_count"])
    state: dict[str, Any] = dict(context["state"])
    _MAX_DDC_BLOCKED_REFRESHES = int(context["max_ddc_blocked_refreshes"])
    while time.time() < deadline:
        _sync_relevant_payment_page(api, prefer_paypal=True)
        active_phone_key = _normalize_paypal_phone(str(active_signup_profile.get("phone") or ""))
        active_phone_submitted = bool(active_phone_key and active_phone_key in submitted_phone_keys)
        if not signup_form_submitted and not active_phone_submitted:
            _force_paypal_us_locale(api, country=paypal_country, lang=paypal_lang)
        current_url = getattr(api.page, "url", "")
        left_host_result = _handle_paypal_left_host(
            current_url=current_url,
            otp_phone_lock_key=otp_phone_lock_key,
            on_progress=on_progress,
        )
        if left_host_result:
            otp_phone_lock_key = _paypal_left_host_values(left_host_result)
            return None
        _ensure_paypal_hosted_captcha_bypass(api)

        # DataDome DDC 检测：每轮都检查可见滑块 / blocked 页面，隐形 DDC iframe 做节流
        if _is_paypal_host(current_url):
            page = getattr(api, "page", None)
            if page:
                blocked_page_result = _handle_paypal_authorize_ddc_blocked_page(
                    api,
                    otp_phone_lock_key=otp_phone_lock_key,
                    ddc_blocked_refresh_count=ddc_blocked_refresh_count,
                    max_ddc_blocked_refreshes=_MAX_DDC_BLOCKED_REFRESHES,
                    on_progress=on_progress,
                )
                if blocked_page_result:
                    otp_phone_lock_key, ddc_blocked_refresh_count = _paypal_authorize_ddc_blocked_page_values(
                        blocked_page_result,
                        otp_phone_lock_key=otp_phone_lock_key,
                        ddc_blocked_refresh_count=ddc_blocked_refresh_count,
                    )
                    if blocked_page_result.get("action") == "continue":
                        continue
                    if blocked_page_result.get("action") == "failed":
                        otp_phone_lock_key, failure_stage, message = _paypal_authorize_datadome_failed_result_fields(
                            blocked_page_result,
                            default_message=f"DataDome 封锁页面刷新 {_MAX_DDC_BLOCKED_REFRESHES} 次仍未恢复",
                        )
                        return _build_result(
                            "failed",
                            failure_stage=failure_stage,
                            message=message,
                            screenshot_paths=screenshot_paths,
                        )

                ddc_challenge_result = _handle_paypal_authorize_ddc_challenge(
                    api,
                    otp_phone_lock_key=otp_phone_lock_key,
                    last_ddc_check_at=last_ddc_check_at,
                    on_progress=on_progress,
                )
                if ddc_challenge_result:
                    otp_phone_lock_key, last_ddc_check_at = _paypal_authorize_ddc_challenge_values(
                        ddc_challenge_result,
                        otp_phone_lock_key=otp_phone_lock_key,
                        last_ddc_check_at=last_ddc_check_at,
                    )
                    if ddc_challenge_result.get("action") == "failed":
                        otp_phone_lock_key, failure_stage, message = _paypal_authorize_datadome_failed_result_fields(
                            ddc_challenge_result,
                            default_message="DataDome 滑块/风控验证未通过",
                        )
                        return _build_result(
                            "failed",
                            failure_stage=failure_stage,
                            message=message,
                            screenshot_paths=screenshot_paths,
                        )

        cancelled_result = _handle_paypal_authorize_cancelled(
            is_cancelled=is_cancelled,
            otp_phone_lock_key=otp_phone_lock_key,
            on_progress=on_progress,
        )
        if cancelled_result:
            otp_phone_lock_key, action, screenshot_label, failure_stage, message = (
                _paypal_authorize_cancelled_result_fields(cancelled_result)
            )
            _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
            return _build_result(
                action,
                failure_stage=failure_stage,
                message=message,
                screenshot_paths=screenshot_paths,
            )

        state = _inspect_and_merge_paypal_state(
            api,
            previous_state=state,
            paypal_ba_token=paypal_ba_token,
        )
        classified = classify_paypal_checkout_state(current_url, state.get("body_text", ""))
        phone_rejected_rotation = _handle_paypal_phone_rejected_rotation(
            api,
            paypal_mode=paypal_mode,
            classified=classified,
            signup_profile_index=signup_profile_index,
            signup_profiles=signup_profiles,
            active_signup_profile=active_signup_profile,
            current_url=current_url,
            otp_phone_lock_key=otp_phone_lock_key,
            on_progress=on_progress,
        )
        if phone_rejected_rotation:
            (
                otp_phone_lock_key,
                signup_profile_index,
                active_signup_profile,
                signup_form_submitted,
                signup_submitted_at,
                phone_only_retry,
                card_retry_count,
            ) = _paypal_phone_rejected_rotation_values(
                phone_rejected_rotation,
                otp_phone_lock_key=otp_phone_lock_key,
                signup_profile_index=signup_profile_index,
                active_signup_profile=active_signup_profile,
                signup_form_submitted=signup_form_submitted,
                signup_submitted_at=signup_submitted_at,
                phone_only_retry=phone_only_retry,
                card_retry_count=card_retry_count,
            )
            continue
        failed_classification = _handle_paypal_authorize_failed_classification(
            api,
            classified=classified,
            paypal_mode=paypal_mode,
            active_signup_profile=active_signup_profile,
            signup_profile_index=signup_profile_index,
            signup_profiles=signup_profiles,
            current_url=current_url,
            otp_phone_lock_key=otp_phone_lock_key,
            ddc_blocked_refresh_count=ddc_blocked_refresh_count,
            max_ddc_blocked_refreshes=_MAX_DDC_BLOCKED_REFRESHES,
            on_progress=on_progress,
        )
        if failed_classification:
            ddc_blocked_refresh_count = _paypal_authorize_classification_refresh_count(
                failed_classification,
                ddc_blocked_refresh_count=ddc_blocked_refresh_count,
            )
            if failed_classification.get("action") == "continue":
                continue
            if failed_classification.get("action") == "return_classified":
                otp_phone_lock_key, screenshot_label, classified_result = _paypal_authorize_classified_return_values(
                    failed_classification,
                    classified,
                    default_screenshot_label="paypal-authorize-failed",
                )
                _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                classified_result["screenshot_paths"] = screenshot_paths
                return classified_result
        review_classification = _handle_paypal_authorize_review_classification(
            api,
            classified=classified,
            otp_phone_lock_key=otp_phone_lock_key,
            ddc_blocked_refresh_count=ddc_blocked_refresh_count,
            max_ddc_blocked_refreshes=_MAX_DDC_BLOCKED_REFRESHES,
            on_progress=on_progress,
        )
        if review_classification:
            ddc_blocked_refresh_count = _paypal_authorize_classification_refresh_count(
                review_classification,
                ddc_blocked_refresh_count=ddc_blocked_refresh_count,
            )
            if review_classification.get("action") == "continue":
                continue
            if review_classification.get("action") == "return_classified":
                otp_phone_lock_key, screenshot_label, classified_result = _paypal_authorize_classified_return_values(
                    review_classification,
                    classified,
                    default_screenshot_label="paypal-authorize-review",
                )
                _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                classified_result["screenshot_paths"] = screenshot_paths
                return classified_result

        if paypal_mode == "create_account":
            _seed_paypal_signup_authorize_state(
                state,
                signup_email_submitted=signup_email_submitted,
                signup_email_submitted_at=signup_email_submitted_at,
                signup_form_submitted=signup_form_submitted,
                signup_submitted_at=signup_submitted_at,
                submitted_phone_keys=submitted_phone_keys,
                phone_only_retry=phone_only_retry,
                card_retry_count=card_retry_count,
                otp_phone_lock_key=otp_phone_lock_key,
            )
            ok, error, handled = _run_paypal_signup_flow(
                api,
                signup_profile=active_signup_profile,
                state=state,
                paypal_country=paypal_country,
                paypal_lang=paypal_lang,
                paypal_ba_token=paypal_ba_token,
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            signup_state = _sync_paypal_signup_authorize_state(
                state,
                signup_email_submitted=signup_email_submitted,
                signup_email_submitted_at=signup_email_submitted_at,
                signup_form_submitted=signup_form_submitted,
                signup_submitted_at=signup_submitted_at,
                card_retry_count=card_retry_count,
            )
            (
                signup_email_submitted,
                signup_email_submitted_at,
                signup_form_submitted,
                signup_submitted_at,
                phone_only_retry,
                card_retry_count,
                otp_phone_lock_key,
            ) = _paypal_signup_authorize_state_values(signup_state)
            stop_before_otp_result = _handle_paypal_signup_stop_before_otp_authorize_result(state)
            if stop_before_otp_result:
                action, screenshot_label, failure_stage, message = _paypal_signup_stop_before_otp_result_fields(
                    stop_before_otp_result
                )
                _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                return _build_result(
                    action,
                    failure_stage=failure_stage,
                    message=message,
                    screenshot_paths=screenshot_paths,
                )
            signup_failure_result = _handle_paypal_signup_flow_failure_authorize_result(
                ok=ok,
                error=error,
                otp_phone_lock_key=otp_phone_lock_key,
                on_progress=on_progress,
            )
            if signup_failure_result:
                otp_phone_lock_key, action, screenshot_label, failure_stage, message = (
                    _paypal_signup_flow_failure_result_fields(signup_failure_result, fallback_error=error)
                )
                _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                return _build_result(
                    action,
                    failure_stage=failure_stage,
                    message=message,
                    screenshot_paths=screenshot_paths,
                )
            if handled:
                continue
            stuck_recover_result = _recover_paypal_signup_unhandled_email_stuck(
                api,
                signup_profile=active_signup_profile,
                state=state,
                signup_email_submitted=signup_email_submitted,
                signup_email_submitted_at=signup_email_submitted_at,
                current_url=getattr(api.page, "url", ""),
                on_progress=on_progress,
            )
            stuck_recover_action = _handle_paypal_signup_stuck_recover_authorize_result(stuck_recover_result)
            if stuck_recover_action:
                if stuck_recover_action.get("action") == "failed":
                    action, screenshot_label, failure_stage, message = (
                        _paypal_signup_stuck_recover_failed_result_fields(stuck_recover_action)
                    )
                    _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                    return _build_result(
                        action,
                        failure_stage=failure_stage,
                        message=message,
                        screenshot_paths=screenshot_paths,
                    )
                if stuck_recover_action.get("action") == "continue":
                    signup_email_submitted, signup_email_submitted_at = _paypal_signup_stuck_recover_continue_values(
                        stuck_recover_action
                    )
                    continue
            login_redirect_result = _handle_paypal_signup_needs_login_redirect(
                api,
                state=state,
                signup_login_redirect_count=signup_login_redirect_count,
                paypal_ba_token=paypal_ba_token,
                paypal_country=paypal_country,
                paypal_lang=paypal_lang,
                on_progress=on_progress,
                sleep_after_redirect_seconds=1.5,
            )
            login_redirect_action = _handle_paypal_signup_login_redirect_authorize_result(login_redirect_result)
            if login_redirect_action:
                if login_redirect_action.get("action") == "continue":
                    (
                        signup_login_redirect_count,
                        signup_email_submitted,
                        signup_email_submitted_at,
                        signup_form_submitted,
                        signup_submitted_at,
                    ) = _paypal_signup_login_redirect_continue_values(login_redirect_action)
                    continue
                if login_redirect_action.get("action") == "failed":
                    action, screenshot_label, failure_stage, message = (
                        _paypal_signup_login_redirect_failed_result_fields(login_redirect_action)
                    )
                    _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                    return _build_result(
                        action,
                        failure_stage=failure_stage,
                        message=message,
                        screenshot_paths=screenshot_paths,
                    )
            visible_state_wait = _handle_paypal_signup_visible_state_wait(state)
            if visible_state_wait:
                continue

        if _maybe_dismiss_paypal_passkey_prompt(api, state=state, on_progress=on_progress):
            continue

        if state.get("needs_login"):
            if paypal_mode == "create_account":
                login_redirect_result = _handle_paypal_signup_needs_login_redirect(
                    api,
                    state=state,
                    signup_login_redirect_count=signup_login_redirect_count,
                    paypal_ba_token=paypal_ba_token,
                    paypal_country=paypal_country,
                    paypal_lang=paypal_lang,
                    on_progress=on_progress,
                )
                login_redirect_action = _handle_paypal_signup_login_redirect_authorize_result(login_redirect_result)
                if login_redirect_action:
                    if login_redirect_action.get("action") == "continue":
                        (
                            signup_login_redirect_count,
                            signup_email_submitted,
                            signup_email_submitted_at,
                            signup_form_submitted,
                            signup_submitted_at,
                        ) = _paypal_signup_login_redirect_continue_values(login_redirect_action)
                        continue
                    if login_redirect_action.get("action") == "failed":
                        action, screenshot_label, failure_stage, message = (
                            _paypal_signup_login_redirect_failed_result_fields(login_redirect_action)
                        )
                        _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                        return _build_result(
                            action,
                            failure_stage=failure_stage,
                            message=message,
                            screenshot_paths=screenshot_paths,
                        )
            ok, error = _submit_paypal_login_step(
                api,
                credentials=effective_credentials,
                state=state,
                on_progress=on_progress,
            )
            login_failure_result = _handle_paypal_login_step_failure_authorize_result(ok=ok, error=error)
            if login_failure_result:
                action, screenshot_label, failure_stage, message = _paypal_login_step_failure_result_fields(
                    login_failure_result,
                    fallback_error=error,
                )
                _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
                return _build_result(
                    action,
                    failure_stage=failure_stage,
                    message=message,
                    screenshot_paths=screenshot_paths,
                )
            continue

        approve_result = _handle_paypal_approve_ready(
            api,
            state=state,
            otp_phone_lock_key=otp_phone_lock_key,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
        if approve_result:
            otp_phone_lock_key, paypal_return_result = _paypal_approve_return_values(approve_result)
            return paypal_return_result

        idle_wait = _handle_paypal_authorize_idle_wait()
        if idle_wait:
            continue

    timeout_result = _handle_paypal_authorize_timeout(
        otp_phone_lock_key=otp_phone_lock_key,
        on_progress=on_progress,
    )
    otp_phone_lock_key, action, screenshot_label, failure_stage, message = _paypal_authorize_timeout_result_fields(
        timeout_result
    )
    _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
    return _build_result(
        action,
        failure_stage=failure_stage,
        message=message,
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
    deadline = _paypal_result_wait_deadline(now=time.time(), timeout_seconds=timeout_seconds)
    last_stage, last_log_at, last_stripe_poll_at, last_ddc_check_at_result = _paypal_result_wait_initial_state()
    autofilled_urls = _paypal_result_autofilled_url_keys()
    stripe_state_http = _paypal_result_stripe_state_http_session(proxy_url)

    while _should_continue_paypal_result_wait(now=time.time(), deadline=deadline):
        _sync_relevant_payment_page(api, prefer_paypal=_paypal_result_sync_prefer_paypal())
        now = time.time()
        should_log_wait, last_log_at = _paypal_result_wait_log_transition(now=now, last_log_at=last_log_at)
        if should_log_wait:
            remaining, log_current_url = _paypal_result_wait_log_values(
                deadline=deadline,
                now=now,
                current_url=getattr(api.page, "url", ""),
            )
            logger.info(
                "[paypal_bind_executor] 等待 PayPal 流程结果，剩余约 %ss，当前 URL=%s",
                remaining,
                log_current_url,
            )

        if _should_cancel_paypal_result_wait(is_cancelled):
            action, screenshot_label, failure_stage, message = _paypal_result_cancelled_result_fields()
            _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
            return _build_result(
                action,
                failure_stage=failure_stage,
                message=message,
                screenshot_paths=screenshot_paths,
            )

        body_text, current_url = _paypal_result_page_snapshot(api)
        if _should_check_paypal_result_datadome(current_url):
            _ensure_paypal_hosted_captcha_bypass(api)
            datadome_result = _handle_paypal_result_datadome_check(
                api,
                last_ddc_check_at=last_ddc_check_at_result,
                on_progress=on_progress,
            )
            if datadome_result:
                last_ddc_check_at_result, should_continue_datadome = _paypal_result_datadome_transition(
                    datadome_result,
                    last_ddc_check_at=last_ddc_check_at_result,
                )
                if should_continue_datadome:
                    continue
        should_run_autofill, autofill_key = _paypal_result_autofill_transition(
            current_url,
            autofill_payload,
            autofilled_url_keys=autofilled_urls,
            autofill_enabled=autofill_enabled,
        )
        if should_run_autofill:
            autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)
            autofilled_urls = _record_paypal_result_autofill_key(autofilled_urls, autofill_key)
        stage, message = _paypal_result_stage_values(current_url, body_text)
        should_emit_stage_progress, last_stage = _paypal_result_stage_progress_transition(
            stage=stage,
            last_stage=last_stage,
        )
        if should_emit_stage_progress:
            progress_stage, progress_message, progress_extra = _paypal_result_stage_progress_event_fields(
                stage=stage,
                message=message,
                current_url=current_url,
            )
            _emit_progress(
                on_progress,
                _progress_event(progress_stage, progress_message, **progress_extra),
            )

        browser_classified_values = _paypal_result_browser_classified_values(current_url, body_text)
        if browser_classified_values:
            screenshot_label, classified_result = browser_classified_values
            return _capture_and_attach_paypal_result_screenshot_paths(
                api,
                session_id=session_id,
                screenshot_label=screenshot_label,
                classified_result=classified_result,
                screenshot_paths=screenshot_paths,
            )

        should_poll_stripe, last_stripe_poll_at = _paypal_result_stripe_poll_transition(
            checkout_url=checkout_url,
            now=now,
            last_poll_at=last_stripe_poll_at,
        )
        if should_poll_stripe:
            stripe_classified = _fetch_paypal_stripe_payment_page_state(checkout_url, http=stripe_state_http)
            if stripe_classified:
                (
                    progress_stage,
                    progress_message,
                    progress_extra,
                    screenshot_label,
                    classified_result,
                ) = _paypal_result_stripe_classified_values(
                    stripe_classified,
                    checkout_url=checkout_url,
                    current_url=current_url,
                )
                _emit_progress(
                    on_progress,
                    _progress_event(
                        progress_stage,
                        progress_message,
                        **progress_extra,
                    ),
                )
                return _capture_and_attach_paypal_result_screenshot_paths(
                    api,
                    session_id=session_id,
                    screenshot_label=screenshot_label,
                    classified_result=classified_result,
                    screenshot_paths=screenshot_paths,
                )

        time.sleep(_paypal_result_wait_sleep_seconds())

    action, screenshot_label, failure_stage, message = _paypal_result_timeout_result_fields()
    _capture_screenshot(api, session_id, screenshot_label, screenshot_paths)
    return _build_result(
        action,
        failure_stage=failure_stage,
        message=message,
        screenshot_paths=screenshot_paths,
    )


def _bounded_timeout_seconds(value: int | None, *, minimum: int, maximum: int) -> int:
    return payment_checkout_state_service.bounded_timeout_seconds(value, minimum=minimum, maximum=maximum)


def _paypal_authorize_timeout_seconds(timeout_seconds: int | None) -> int:
    return payment_checkout_state_service.paypal_authorize_timeout_seconds(timeout_seconds)


def _paypal_result_timeout_seconds(timeout_seconds: int | None) -> int:
    return payment_checkout_state_service.paypal_result_timeout_seconds(timeout_seconds)


def _paypal_checkout_payload(*, country: str = "US", currency: str = "USD", checkout_ui_mode: str = "hosted"):
    """Generate a checkout payload for PayPal extraction.

    The BA extraction path follows pplink: EU mode uses FR/EUR/custom
    with openai_ie, while US mode uses US/USD/hosted with openai_llc.
    """
    return paypal_billing_agreement_service.paypal_checkout_payload(
        country=country,
        currency=currency,
        checkout_ui_mode=checkout_ui_mode,
    )


def _paypal_extract_result_from_redirect(
    http: Any, redirect_url: str, checkout_session_id: str, pm_id: str
) -> dict[str, Any]:
    return paypal_billing_agreement_service.paypal_extract_result_from_redirect(
        http,
        redirect_url,
        checkout_session_id,
        pm_id,
        resolve_approve_url=_paypal_protocol_resolve_approve_url,
    )


def _paypal_pplink_extract_mode(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z]", "", str(value or "").lower())
    if normalized in {"us", "eu", "br", "gb"}:
        return normalized
    if normalized in {"brbrl", "brazil", "brasil"}:
        return "br"
    return "eu"


def _paypal_pplink_checkout_config(mode: str) -> dict[str, str]:
    normalized_mode = _paypal_pplink_extract_mode(mode)
    if normalized_mode == "us":
        return {
            "mode": "us",
            "country": "US",
            "currency": "USD",
            "checkout_ui_mode": "custom",
            "processor_entity": "openai_llc",
            "payment_method_country": "US",
        }
    if normalized_mode == "br":
        return {
            "mode": "br",
            "country": "BR",
            "currency": "BRL",
            "checkout_ui_mode": "custom",
            "processor_entity": "openai_ie",
            "payment_method_country": "BR",
        }
    if normalized_mode == "gb":
        return {
            "mode": "gb",
            "country": "GB",
            "currency": "GBP",
            "checkout_ui_mode": "custom",
            "processor_entity": "openai_ie",
            "payment_method_country": "JP",
        }
    return {
        "mode": "eu",
        "country": "FR",
        "currency": "EUR",
        "checkout_ui_mode": "custom",
        "processor_entity": "openai_ie",
        "payment_method_country": "US",
    }


def _paypal_opll_extract_processor_entity(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("processor_entity") or data.get("processorEntity")
    if direct:
        return str(direct).strip()
    for key in ("checkout_session", "session", "checkout", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = _paypal_opll_extract_processor_entity(nested)
            if found:
                return found
    return ""


def _paypal_opll_extract_stripe_publishable_key(data: Any) -> str:
    if isinstance(data, str):
        match = re.search(r"pk_live_[A-Za-z0-9]+", data)
        return match.group(0) if match else ""
    if isinstance(data, dict):
        for key in ("stripe_publishable_key", "publishable_key", "publishableKey", "stripePublishableKey", "key"):
            found = _paypal_opll_extract_stripe_publishable_key(data.get(key))
            if found:
                return found
        for item in data.values():
            found = _paypal_opll_extract_stripe_publishable_key(item)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _paypal_opll_extract_stripe_publishable_key(item)
            if found:
                return found
    return ""


def _paypal_opll_processor_entity_for_country(country: str, processor_entity: str = "") -> str:
    entity = str(processor_entity or "").strip()
    if entity:
        return entity
    return "openai_llc" if str(country or "").upper() == "US" else "openai_ie"


def _paypal_opll_chatgpt_success_return_url(
    checkout_session_id: str,
    country: str,
    processor_entity: str = "",
) -> str:
    entity = _paypal_opll_processor_entity_for_country(country, processor_entity)
    return (
        "https://chatgpt.com/checkout/verify"
        f"?stripe_session_id={checkout_session_id}&processor_entity={entity}&plan_type=plus"
    )


def _paypal_opll_to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]
    parsed = urlsplit(url)
    if parsed.netloc.lower() == "checkout.stripe.com":
        return urlunsplit((parsed.scheme or "https", "pay.openai.com", parsed.path, parsed.query, parsed.fragment))
    return url


def _paypal_opll_stripe_checkout_long_url(
    checkout_session_id: str,
    country: str,
    processor_entity: str = "",
) -> str:
    return (
        f"https://checkout.stripe.com/c/pay/{checkout_session_id}"
        "?returned_from_redirect=true&ui_mode=custom&return_url="
        f"{quote(_paypal_opll_chatgpt_success_return_url(checkout_session_id, country, processor_entity), safe='')}"
    )


def _paypal_opll_confirm_return_url(checkout_session_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = _paypal_opll_to_openai_pay_url(stripe_hosted_url) or _paypal_opll_stripe_checkout_long_url(
        checkout_session_id,
        str(checkout.get("billing_country") or "US"),
        str(checkout.get("processor_entity") or ""),
    )
    if "pay.openai.com/" in hosted_url or "checkout.stripe.com/" in hosted_url:
        parsed = urlsplit(hosted_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault(
            "success_return_url",
            _paypal_opll_chatgpt_success_return_url(
                checkout_session_id,
                str(checkout.get("billing_country") or "US"),
                str(checkout.get("processor_entity") or ""),
            ),
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return hosted_url


def _paypal_opll_collect_urls(payload: Any, urls: list[str] | None = None) -> list[str]:
    found = urls if urls is not None else []
    if isinstance(payload, str):
        for match in re.findall(r"https?://[^\s\"'<>]+", payload):
            found.append(match.rstrip("),.;]"))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"url", "return_url", "redirect_url", "redirect_to_url"} and isinstance(value, str):
                found.append(value)
            else:
                _paypal_opll_collect_urls(value, found)
    elif isinstance(payload, list):
        for item in payload:
            _paypal_opll_collect_urls(item, found)
    return found


def _paypal_opll_find_submission_attempt(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        item = payload.get("submission_attempt")
        if isinstance(item, dict):
            return item
        for value in payload.values():
            found = _paypal_opll_find_submission_attempt(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _paypal_opll_find_submission_attempt(value)
            if found:
                return found
    return {}


def _paypal_opll_redirect_from_payload(payload: Any) -> str:
    redirect_url = _find_paypal_redirect_url(payload)
    if redirect_url:
        return redirect_url
    for url in _paypal_opll_collect_urls(payload):
        lowered = str(url or "").lower()
        if "pm-redirects.stripe.com" in lowered or "paypal.com" in lowered:
            return str(url or "").strip()
    return ""


def _paypal_opll_submission_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return f"payload_type={type(payload).__name__}"
    submission = _paypal_opll_find_submission_attempt(payload)
    if not submission:
        return f"keys={sorted(payload.keys())[:12]}"
    return "submission_attempt.state=" + str(submission.get("state") or "unknown")


def _paypal_opll_should_retry_with_requests(exc: BaseException, http: Any) -> bool:
    if payment_http_service.http_transport_name(http) != "curl_cffi":
        return False
    message = str(exc).lower()
    return "getaddrinfo() thread failed to start" in message


def _paypal_opll_configure_chatgpt_http_session(
    http: Any,
    *,
    access_token: str,
    device_id: str,
    user_agent: str,
) -> None:
    token = str(access_token or "").strip()
    http.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {token}" if token else "",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-US",
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    if not token:
        http.headers.pop("Authorization", None)


def _paypal_pplink_extract_html_context(text: str) -> dict[str, Any]:
    body = str(text or "")
    pk_match = re.search(r"pk_live_[A-Za-z0-9_]+", body)
    secret_match = re.search(r"seti_[A-Za-z0-9_]+_secret_[A-Za-z0-9_]+", body)
    amount = 0
    for key in ("amount_total", "amount_due", "total_amount_due"):
        match = re.search(rf'{key}"?\s*:?\s*([0-9]+)', body)
        if match:
            amount = int(match.group(1) or "0")
            break
    return {
        "publishable_key": pk_match.group(0) if pk_match else "",
        "client_secret": secret_match.group(0) if secret_match else "",
        "amount": amount,
    }


def _paypal_pplink_billing_profile(*, country: str, access_token: str) -> dict[str, str]:
    normalized_country = re.sub(r"[^A-Za-z]", "", str(country or "")).upper()[:2] or "JP"
    names = [
        ("Alex", "Tan"),
        ("Daniel", "Lee"),
        ("Emma", "Wong"),
        ("Mia", "Chen"),
        ("Noah", "Martin"),
        ("Olivia", "Nguyen"),
    ]
    phone_prefixes = {"AU": "+61", "BR": "+55", "CA": "+1", "DE": "+49", "FR": "+33", "GB": "+44", "JP": "+81", "US": "+1"}

    def profile_email(first: str, last: str) -> str:
        return f"{first.lower()}.{last.lower()}{random.randint(1000, 9999)}@example.com"

    def profile_phone(country_code: str) -> str:
        return f"{phone_prefixes.get(country_code, '+1')}{random.randint(100000000, 999999999)}"

    if normalized_country == "JP":
        profile = dict(
            random.choice(
                [
                    {
                        "name": "Taro Yamada",
                        "country": "JP",
                        "state": "Tokyo",
                        "city": "Tokyo",
                        "postal_code": "101-8656",
                        "line1": "1-1 Kanda Ogawamachi",
                    },
                    {
                        "name": "Ken Sato",
                        "country": "JP",
                        "state": "Aichi",
                        "city": "Nagoya",
                        "postal_code": "460-0002",
                        "line1": "1-1 Marunouchi",
                    },
                ]
            )
        )
        first, last = str(profile["name"]).split(" ", 1)
        profile["email"] = profile_email(first, last)
        profile["phone"] = profile_phone("JP")
        return profile
    if normalized_country == "AU":
        first, last = random.choice([("Oliver", "Wilson"), ("Jack", "Taylor"), ("Amelia", "Brown")])
        line1, city, state, postal = random.choice(
            [
                ("10 George Street", "Sydney", "NSW", "2000"),
                ("525 Collins Street", "Melbourne", "VIC", "3000"),
                ("22 King William Street", "Adelaide", "South Australia", "5000"),
            ]
        )
        return {
            "name": f"{first} {last}",
            "email": profile_email(first, last),
            "phone": profile_phone("AU"),
            "country": "AU",
            "state": state,
            "city": city,
            "postal_code": postal,
            "line1": line1,
        }
    if normalized_country == "US":
        first, last = random.choice(
            [
                ("James", "Smith"),
                ("John", "Brown"),
                ("Michael", "Johnson"),
                ("Robert", "Miller"),
                ("David", "Davis"),
                ("William", "Wilson"),
            ]
        )
        line1, city, state, postal = random.choice(
            [
                ("3110 Sunset Boulevard", "Los Angeles", "CA", "90026"),
                ("1200 Market Street", "San Francisco", "CA", "94102"),
                ("500 Main Street", "Austin", "TX", "78701"),
                ("88 Broadway", "New York", "NY", "10007"),
                ("1200 Peachtree St", "Atlanta", "GA", "30309"),
            ]
        )
        return {
            "name": f"{first} {last}",
            "email": profile_email(first, last),
            "phone": profile_phone("US"),
            "country": "US",
            "state": state,
            "city": city,
            "postal_code": postal,
            "line1": line1,
        }
    if normalized_country == "BR":
        first, last = random.choice(names)
        return {
            "name": f"{first} {last}",
            "email": profile_email(first, last),
            "phone": profile_phone("BR"),
            "country": "BR",
            "state": "BR",
            "city": random.choice(["Sao Paulo", "Rio de Janeiro", "Brasilia"]),
            "postal_code": f"{random.randint(10000, 99999)}-{random.randint(100, 999)}",
            "line1": f"{random.randint(10, 999)} {random.choice(['Market Street', 'Central Avenue', 'Station Road', 'Main Street', 'High Street', 'King Street'])}",
        }
    first, last = random.choice(names)
    return {
        "name": f"{first} {last}",
        "email": profile_email(first, last),
        "phone": profile_phone(normalized_country),
        "country": normalized_country,
        "state": normalized_country,
        "city": "Capital City",
        "postal_code": str(random.randint(10000, 99999)),
        "line1": f"{random.randint(10, 999)} Market Street",
    }


def _paypal_pplink_redirect_from_response(resp: Any) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = None
    redirect_url = _find_paypal_redirect_url(payload) if payload is not None else ""
    if redirect_url:
        return redirect_url
    text = str(getattr(resp, "text", "") or "")
    return _find_paypal_redirect_url(text)


def _paypal_pplink_approve_checkout(
    http: Any,
    *,
    access_token: str,
    checkout_session_id: str,
    processor_entity: str,
    client_session_id: str,
    cookie_header: str = "",
    account_id: str = "",
    device_id: str = "",
) -> dict[str, Any]:
    approve_path = "/backend-api/payments/checkout/approve"
    headers = _chatgpt_checkout_headers(
        access_token=access_token,
        checkout_session_id=checkout_session_id,
        processor_entity=processor_entity,
        cookie_header=cookie_header or _cookie_header_from_http_session(http),
        account_id=account_id,
        device_id=device_id,
        target_path=approve_path,
        openai_sentinel_token="",
    )
    headers["content-type"] = "application/x-www-form-urlencoded"
    data = {
        "checkout_session_id": checkout_session_id,
        "processor_entity": processor_entity,
        "client_attribution_metadata[client_session_id]": client_session_id,
        "client_attribution_metadata[merchant_integration_source]": "custom_checkout_manual_approval_1",
        "client_attribution_metadata[merchant_integration_version]": "2020-08-27;custom_checkout_beta=v1",
    }
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        data=data,
        headers=headers,
        timeout=30,
    )
    if int(getattr(resp, "status_code", 0) or 0) >= 300:
        raise GoPayFlowError(
            f"ChatGPT approve 失败: HTTP {resp.status_code} {str(getattr(resp, 'text', '') or '')[:500]}",
            stage="chatgpt_approve",
        )
    payload = _response_json(resp, "paypal_chatgpt_approve")
    if payload.get("result") not in (None, "approved"):
        raise GoPayFlowError(f"ChatGPT approve 未通过: {payload}", stage="chatgpt_approve")
    return payload


def _paypal_pplink_exe_path() -> Path:
    override = str(os.environ.get("PAYPAL_BA_PPLINK_EXE") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[3] / "vendor" / "pplink" / "pplink.exe"


def _paypal_pplink_parse_authorize_url(output: str) -> str:
    match = re.search(r"Authorize URL:\s*(\S+)", str(output or ""), flags=re.IGNORECASE)
    if match:
        return _paypal_protocol_unescape_url(match.group(1).strip())
    return _find_paypal_redirect_url(output)


def _paypal_pplink_parse_checkout_session_id(output: str) -> str:
    match = re.search(r"\b(cs_(?:live|test)_[A-Za-z0-9_]+|cs_[A-Za-z0-9_]+)\b", str(output or ""))
    return match.group(1) if match else ""


def _paypal_pplink_normalize_proxy_url(value: str | None) -> str:
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    scheme_idx = proxy.find("://")
    at_idx = proxy.rfind("@")
    if scheme_idx > 0 and at_idx > scheme_idx:
        userinfo_start = scheme_idx + 3
        userinfo = proxy[userinfo_start:at_idx]
        return proxy[:userinfo_start] + quote(userinfo, safe=":%") + proxy[at_idx:]
    return proxy.replace(" ", "%20")


def _paypal_pplink_proxy_config(
    *,
    mode: str,
    proxy_url: str | None,
    provider_proxy_url: str | None,
    approve_proxy_url: str | None,
) -> dict[str, str]:
    primary_proxy = _paypal_pplink_normalize_proxy_url(proxy_url)
    provider_proxy = _paypal_pplink_normalize_proxy_url(provider_proxy_url)
    approve_proxy = _paypal_pplink_normalize_proxy_url(approve_proxy_url)
    if mode == "us":
        us_proxy = provider_proxy or approve_proxy or primary_proxy
        return {"proxy_jp": primary_proxy or us_proxy, "proxy_us": us_proxy}
    return {"proxy_jp": primary_proxy, "proxy_us": provider_proxy or approve_proxy}


def _paypal_pplink_run_exe(
    *,
    access_token: str,
    proxy_url: str | None,
    provider_proxy_url: str | None,
    approve_proxy_url: str | None,
    paypal_ba_mode: str,
    timeout_seconds: int,
    is_cancelled=None,
    on_progress=None,
) -> dict[str, Any]:
    if callable(is_cancelled) and is_cancelled():
        return {"status": "failed", "failure_stage": "extract_ba_link", "message": "Task cancelled"}

    token = str(access_token or "").strip()
    if not token:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_pplink",
            "message": "pplink 缺少 ChatGPT access_token",
        }

    exe_path = _paypal_pplink_exe_path()
    if not exe_path.exists():
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_pplink",
            "message": f"未找到项目内 pplink.exe: {exe_path}",
        }

    mode = _paypal_pplink_extract_mode(paypal_ba_mode)
    config = _paypal_pplink_checkout_config(mode)
    processor_entity = str(os.environ.get("PAYPAL_BA_PROCESSOR_ENTITY") or config["processor_entity"]).strip()
    proxy_config = _paypal_pplink_proxy_config(
        mode=mode,
        proxy_url=proxy_url,
        provider_proxy_url=provider_proxy_url,
        approve_proxy_url=approve_proxy_url,
    )
    if not proxy_config.get("proxy_jp") and not proxy_config.get("proxy_us"):
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_pplink",
            "message": "pplink 缺少代理配置",
            "paypal_ba_mode": mode,
        }

    _emit = _progress_adapter(on_progress)
    _emit("paypal_extract_pplink_start", message=f"Running bundled pplink.exe ({mode.upper()})")
    max_retry = str(os.environ.get("PAYPAL_BA_PPLINK_MAX_RETRY") or "1").strip() or "1"
    retry_wait = str(os.environ.get("PAYPAL_BA_PPLINK_RETRY_WAIT") or "0").strip() or "0"
    stop_at_pm = str(os.environ.get("PAYPAL_BA_PPLINK_STOP_PM") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    run_timeout = max(90, int(timeout_seconds or 90) + 90)

    with tempfile.TemporaryDirectory(prefix="autotoken-pplink-") as tmp:
        config_path = Path(tmp) / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "proxy_jp": proxy_config.get("proxy_jp", ""),
                    "proxy_us": proxy_config.get("proxy_us", ""),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        args = [
            str(exe_path),
            "-config",
            str(config_path),
            "-mode",
            mode,
            "-max-retry",
            max_retry,
            "-retry-wait",
            retry_wait,
        ]
        if stop_at_pm:
            args.append("-stop-at-pm-redirects")
        if processor_entity:
            args.extend(["-entity", processor_entity])
        args.extend(["-token", token])
        env = os.environ.copy()
        env["PP_MODE"] = mode
        if processor_entity:
            env["PP_ENTITY"] = processor_entity
        env["PP_MAX_RETRY"] = max_retry
        env["PP_RETRY_WAIT"] = retry_wait
        env["PP_STOP_PM"] = "1" if stop_at_pm else "0"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.run(
                args,
                cwd=tmp,
                env=env,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=run_timeout,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_pplink_timeout",
                "message": f"pplink.exe 超时: {exc}",
                "paypal_ba_mode": mode,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_pplink",
                "message": f"pplink.exe 启动失败: {exc}",
                "paypal_ba_mode": mode,
            }

    output = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    checkout_session_id = _paypal_pplink_parse_checkout_session_id(output)
    authorize_url = _paypal_pplink_parse_authorize_url(output)
    if proc.returncode != 0 or not authorize_url:
        excerpt = _compact_log_text(output[-1200:], limit=1200)
        message = f"pplink.exe 提取失败: exit={proc.returncode}"
        if excerpt:
            message = f"{message}; output={excerpt}"
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_pplink",
            "message": message,
            "checkout_session_id": checkout_session_id,
            "paypal_ba_mode": mode,
        }

    _emit(
        "paypal_extract_pplink_url",
        message="pplink.exe extracted PayPal authorize URL",
        url=_safe_url_summary(authorize_url),
        checkout_session_id=checkout_session_id,
    )
    resolver_proxy = (
        str(provider_proxy_url or "").strip()
        or str(approve_proxy_url or "").strip()
        or str(proxy_url or "").strip()
        or None
    )
    resolve_http = _new_http_session(resolver_proxy, require_curl_cffi=False)
    result = _paypal_extract_result_from_redirect(resolve_http, authorize_url, checkout_session_id, "")
    result.setdefault("approve_url", authorize_url)
    result.setdefault("checkout_url", f"https://pay.openai.com/c/pay/{checkout_session_id}" if checkout_session_id else "")
    result.setdefault("hosted_checkout_url", result.get("checkout_url", ""))
    result.setdefault("paypal_ba_mode", mode)
    if paypal_billing_agreement_service.paypal_ba_extract_succeeded(result):
        _emit(
            "paypal_extract_done",
            message=f"Extracted BA token: {result.get('ba_token')}",
            ba_token=result.get("ba_token"),
            approve_url=result.get("approve_url"),
        )
    return result


def _paypal_extract_ba_link(
    *,
    access_token: str,
    session_token: str = "",
    account_id: str = "",
    device_id: str = "",
    cookie_header: str = "",
    user_agent: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
    proxy_url: str | None = None,
    provider_proxy_url: str | None = None,
    approve_proxy_url: str | None = None,
    country: str = "US",
    currency: str = "USD",
    payment_method_country: str | None = None,
    paypal_ba_mode: str = "eu",
    timeout_seconds: int = 90,
    is_cancelled=None,
    on_progress=None,
):
    backend = str(os.environ.get("PAYPAL_BA_EXTRACT_BACKEND") or "python").strip().lower()
    pm_country = re.sub(r"[^A-Za-z]", "", str(payment_method_country or "").strip().upper())[:2]
    has_session_context = bool(str(session_token or "").strip() or str(cookie_header or "").strip())
    use_pplink_backend = backend in {"pplink", "pplink_exe", "exe", "legacy"}
    if not use_pplink_backend or bool(pm_country and pm_country != "US") or has_session_context:
        return _paypal_extract_ba_link_python(
            access_token=access_token,
            session_token=session_token,
            account_id=account_id,
            device_id=device_id,
            cookie_header=cookie_header,
            user_agent=user_agent,
            openai_sentinel_token=openai_sentinel_token,
            oai_client_version=oai_client_version,
            oai_client_build_number=oai_client_build_number,
            proxy_url=proxy_url,
            provider_proxy_url=provider_proxy_url,
            approve_proxy_url=approve_proxy_url,
            country=country,
            currency=currency,
            payment_method_country=payment_method_country,
            paypal_ba_mode=paypal_ba_mode,
            timeout_seconds=timeout_seconds,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
    return _paypal_pplink_run_exe(
        access_token=access_token,
        proxy_url=proxy_url,
        provider_proxy_url=provider_proxy_url,
        approve_proxy_url=approve_proxy_url,
        paypal_ba_mode=paypal_ba_mode,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    )



def _paypal_extract_ba_link_python(
    *,
    access_token: str,
    session_token: str = "",
    account_id: str = "",
    device_id: str = "",
    cookie_header: str = "",
    user_agent: str = "",
    openai_sentinel_token: str = "",
    oai_client_version: str = "",
    oai_client_build_number: str = "",
    proxy_url: str | None = None,
    provider_proxy_url: str | None = None,
    approve_proxy_url: str | None = None,
    country: str = "US",
    currency: str = "USD",
    payment_method_country: str | None = None,
    paypal_ba_mode: str = "eu",
    timeout_seconds: int = 90,
    is_cancelled=None,
    on_progress=None,
):
    """Extract a PayPal BA link with the OPLL custom checkout protocol flow."""
    if callable(is_cancelled) and is_cancelled():
        return {"status": "failed", "failure_stage": "extract_ba_link", "message": "Task cancelled"}

    mode = _paypal_pplink_extract_mode(paypal_ba_mode)
    config = _paypal_pplink_checkout_config(mode)
    checkout_country = str(os.environ.get("PAYPAL_BA_CHECKOUT_COUNTRY") or config["country"]).strip().upper()
    checkout_currency = str(os.environ.get("PAYPAL_BA_CHECKOUT_CURRENCY") or config["currency"]).strip().upper()
    checkout_ui_mode = str(os.environ.get("PAYPAL_BA_CHECKOUT_UI_MODE") or "custom").strip().lower()
    processor_entity = str(os.environ.get("PAYPAL_BA_PROCESSOR_ENTITY") or config["processor_entity"]).strip()
    pm_country = str(payment_method_country or config["payment_method_country"]).strip().upper()
    if mode == "us" and not payment_method_country:
        pm_country = "US"

    chrome_ua = (
        str(user_agent or "").strip()
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    )
    resolved_device_id = str(device_id or "").strip() or str(uuid.uuid4())
    _emit = _progress_adapter(on_progress)

    chat_proxy = str(proxy_url or "").strip() or None
    stripe_proxy = str(provider_proxy_url or "").strip() if mode in {"us", "gb"} else ""
    if not stripe_proxy:
        stripe_proxy = str(proxy_url or "").strip()

    if mode == "gb":
        proxy_seed = str(chat_proxy or stripe_proxy or "").strip()
        chat_proxy = proxy_runtime_service.proxy_url_for_region_and_sid(
            proxy_seed,
            "GB",
            secrets.token_hex(6),
        ) or None
        stripe_proxy = proxy_runtime_service.proxy_url_for_region_and_sid(
            str(stripe_proxy or proxy_seed),
            "JP",
            secrets.token_hex(6),
        )

    def _configure_opll_chat_http(chat_session: Any) -> None:
        _paypal_opll_configure_chatgpt_http_session(
            chat_session,
            access_token=access_token,
            device_id=resolved_device_id,
            user_agent=chrome_ua,
        )
        chat_session.headers.update(
            {
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://chatgpt.com",
                "Referer": "https://chatgpt.com/",
            }
        )

    def _build_opll_http_sessions(*, force_requests: bool = False) -> tuple[Any, Any, Any | None]:
        chat_http = _new_http_session(chat_proxy, require_curl_cffi=False, force_requests=force_requests)
        _configure_opll_chat_http(chat_http)
        update_http = None
        if mode == "gb":
            update_http = _new_http_session(
                stripe_proxy or None,
                require_curl_cffi=False,
                force_requests=force_requests,
            )
            _configure_opll_chat_http(update_http)
        payment_http = _new_http_session(stripe_proxy or None, require_curl_cffi=False, force_requests=force_requests)
        payment_http.headers.update({"User-Agent": chrome_ua, "Accept": "application/json"})
        return chat_http, payment_http, update_http

    http, stripe_http, checkout_update_http = _build_opll_http_sessions()

    _emit("paypal_extract_warmup", message=f"Warming up ChatGPT session ({mode.upper()})")
    try:
        http.get(
            "https://chatgpt.com/backend-api/sentinel/ping",
            headers={"Referer": "https://chatgpt.com/", "x-openai-target-path": "/backend-api/sentinel/ping"},
            timeout=30,
        )
    except Exception as exc:
        logger.info("[paypal_extract] OPLL warmup soft-failed: %s", exc)

    _emit("paypal_extract_checkout", message=f"Creating OPLL {mode.upper()} checkout session")
    payload = _paypal_checkout_payload(
        country=checkout_country,
        currency=checkout_currency,
        checkout_ui_mode=checkout_ui_mode,
    )
    try:
        resp = http.post("https://chatgpt.com/backend-api/payments/checkout", json=payload, timeout=30)
    except Exception as exc:
        if _paypal_opll_should_retry_with_requests(exc, http):
            logger.info("[paypal_extract] curl_cffi checkout failed on proxy DNS thread, retrying with requests: %s", exc)
            _emit("paypal_extract_checkout_retry", message="Retrying OPLL checkout with requests transport")
            http, stripe_http, checkout_update_http = _build_opll_http_sessions(force_requests=True)
            try:
                http.get(
                    "https://chatgpt.com/backend-api/sentinel/ping",
                    headers={"Referer": "https://chatgpt.com/", "x-openai-target-path": "/backend-api/sentinel/ping"},
                    timeout=30,
                )
            except Exception as warmup_exc:
                logger.info("[paypal_extract] OPLL requests retry warmup soft-failed: %s", warmup_exc)
            try:
                resp = http.post("https://chatgpt.com/backend-api/payments/checkout", json=payload, timeout=30)
            except Exception as retry_exc:
                return {
                    "status": "failed",
                    "failure_stage": "extract_ba_link_checkout",
                    "message": f"ChatGPT checkout request failed after requests retry: {retry_exc}",
                }
        else:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_checkout",
                "message": f"ChatGPT checkout request failed: {exc}",
            }
    if int(getattr(resp, "status_code", 0) or 0) >= 300:
        response_text = str(getattr(resp, "text", "") or "")
        if int(getattr(resp, "status_code", 0) or 0) == 401 and (
            "token_invalidated" in response_text.lower()
            or "authentication token has been invalidated" in response_text.lower()
            or "token_revoked" in response_text.lower()
            or "invalidated oauth token" in response_text.lower()
        ):
            return {
                "status": "failed",
                "failure_stage": "token_invalidated",
                "token_invalidated": True,
                "message": f"ChatGPT checkout HTTP {resp.status_code}: {response_text[:500]}",
            }
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_checkout",
            "message": f"ChatGPT checkout HTTP {resp.status_code}: {response_text[:500]}",
        }
    data = _response_json(resp, "paypal_extract_checkout")
    cs_id = str(data.get("checkout_session_id") or data.get("session_id") or data.get("id") or "").strip()
    if not cs_id.startswith("cs_"):
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_checkout",
            "message": f"Invalid checkout session id: {cs_id}",
        }
    processor_entity = _paypal_opll_extract_processor_entity(data) or processor_entity
    stripe_pk = _paypal_opll_extract_stripe_publishable_key(data) or DEFAULT_STRIPE_PK
    hosted_checkout_url = _paypal_opll_to_openai_pay_url(
        str(data.get("stripe_hosted_url") or data.get("url") or data.get("checkout_url") or "").strip()
    )
    if not hosted_checkout_url:
        hosted_checkout_url = f"https://pay.openai.com/c/pay/{cs_id}"
    logger.info(
        "[paypal_extract] opll mode=%s cs=%s entity=%s checkout=%s/%s/%s",
        mode,
        cs_id,
        processor_entity,
        checkout_country,
        checkout_currency,
        checkout_ui_mode,
    )

    if mode == "gb":
        _emit("paypal_extract_checkout_update", message="Updating GB checkout from JP")
        update_payload = {
            "checkout_session_id": cs_id,
            "processor_entity": processor_entity,
            "plan_name": "chatgptplusplan",
            "price_interval": "month",
            "seat_quantity": 1,
            "discount_code": None,
            "promo_campaign": {
                "promo_campaign_id": "plus-1-month-free",
                "is_coupon_from_query_param": False,
            },
        }
        try:
            update_resp = checkout_update_http.post(
                "https://chatgpt.com/backend-api/payments/checkout/update",
                json=update_payload,
                headers={
                    "x-openai-target-path": "/backend-api/payments/checkout/update",
                    "x-openai-target-route": "/backend-api/payments/checkout/update",
                },
                timeout=30,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_checkout_update",
                "message": f"ChatGPT checkout update request failed: {exc}",
                "checkout_session_id": cs_id,
                "paypal_ba_mode": mode,
            }
        if int(getattr(update_resp, "status_code", 0) or 0) >= 300:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_checkout_update",
                "message": (
                    f"ChatGPT checkout update HTTP {update_resp.status_code}: "
                    f"{str(getattr(update_resp, 'text', '') or '')[:500]}"
                ),
                "checkout_session_id": cs_id,
                "paypal_ba_mode": mode,
            }
        update_result = _response_json(update_resp, "paypal_extract_checkout_update")
        if update_result.get("success") is not True:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_checkout_update",
                "message": f"ChatGPT checkout update rejected: {update_result}",
                "checkout_session_id": cs_id,
                "paypal_ba_mode": mode,
            }

    _emit("paypal_extract_stripe_init", message="Initializing Stripe payment_page")
    try:
        init_ctx = _paypal_protocol_stripe_init(stripe_http, cs_id, stripe_pk)
    except Exception as exc:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_stripe_init",
            "message": f"Stripe payment_page init failed: {exc}",
            "checkout_session_id": cs_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }
    init_ctx["processor_entity"] = processor_entity
    init_ctx["billing_country"] = checkout_country
    init_ctx["stripe_pk"] = stripe_pk
    if init_ctx.get("stripe_hosted_url"):
        hosted_checkout_url = _paypal_opll_to_openai_pay_url(str(init_ctx.get("stripe_hosted_url") or "")) or hosted_checkout_url
    amount = _paypal_protocol_amount_due(init_ctx.get("expected_amount"))
    logger.info("[paypal_extract] opll init pk=%s amount=%d", stripe_pk[:18], amount)
    if amount != 0:
        nonzero_email = _email_from_access_token(access_token)
        _emit(
            "paypal_extract_nonzero_amount_blocked",
            message=f"BA 提取检测到 checkout 今日应付金额非 0 ({amount})，已停止",
            expected_amount=str(amount),
            currency=checkout_currency.lower(),
        )
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_nonzero_amount",
            "message": f"BA 提取检测到 checkout 今日应付金额非 0 ({amount})，已停止",
            "checkout_session_id": cs_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "nonzero_amount": amount,
            "nonzero_blocked_emails": [nonzero_email] if nonzero_email else [],
            "paypal_ba_mode": mode,
        }

    billing_profile = _paypal_pplink_billing_profile(country=pm_country, access_token=access_token)
    billing_for_checkout = {
        "name": billing_profile["name"],
        "email": billing_profile["email"],
        "phone": billing_profile.get("phone") or "",
        "country": billing_profile["country"],
        "state": billing_profile["state"],
        "city": billing_profile["city"],
        "zip": billing_profile["postal_code"],
        "address1": billing_profile["line1"],
    }
    payment_method_types = init_ctx.get("payment_method_types") or _paypal_protocol_payment_method_types(init_ctx.get("raw"))
    link_shortcut_available = amount == 0 and {"link", "paypal"}.issubset(set(payment_method_types or set()))
    if payment_method_types and "paypal" not in payment_method_types:
        return {
            "status": "failed",
            "failure_stage": "paypal_payment_method_unavailable",
            "message": (
                "当前 checkout session 未启用 PayPal 支付方式 "
                f"(payment_method_types={','.join(sorted(payment_method_types))})，"
                "请重新生成支持 PayPal 的 checkout 后再提取 BA 链接"
            ),
            "checkout_session_id": cs_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }

    _emit("paypal_extract_pm", message=f"Creating PayPal payment method ({billing_profile['country']})")
    try:
        pm_id = _paypal_protocol_create_payment_method(
            stripe_http,
            cs_id,
            stripe_pk,
            init_ctx,
            billing_for_checkout,
            billing_profile["email"],
        )
        _emit("paypal_extract_confirm", message="Confirming payment_page with PayPal PM")
        confirm_payload = _paypal_protocol_confirm_checkout(stripe_http, hosted_checkout_url, cs_id, stripe_pk, init_ctx, pm_id)
    except Exception as exc:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_confirm",
            "message": f"Stripe payment_page confirm failed: {exc}",
            "checkout_session_id": cs_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }

    def result_from_redirect(redirect_url: str) -> dict[str, Any]:
        _emit("paypal_extract_resolve", message="Resolving final PayPal URL")
        result = _paypal_extract_result_from_redirect(stripe_http, redirect_url, cs_id, pm_id)
        result.setdefault("checkout_url", hosted_checkout_url)
        result.setdefault("hosted_checkout_url", hosted_checkout_url)
        result.setdefault("paypal_ba_mode", mode)
        result.setdefault("payment_method_types", sorted(payment_method_types or []))
        result.setdefault("link_shortcut_available", link_shortcut_available)
        if paypal_billing_agreement_service.paypal_ba_extract_succeeded(result):
            _emit(
                "paypal_extract_done",
                message=f"Extracted PayPal redirect: {result.get('approve_url') or result.get('provider_redirect_url')}",
                ba_token=result.get("ba_token"),
                approve_url=result.get("approve_url"),
            )
        elif paypal_billing_agreement_service.paypal_payment_link_extract_succeeded(result):
            _emit(
                "paypal_extract_redirect_ready",
                message="Extracted usable PayPal redirect",
                approve_url=result.get("approve_url"),
            )
        return result

    redirect_url = _paypal_opll_redirect_from_payload(confirm_payload)
    if redirect_url:
        return result_from_redirect(redirect_url)
    confirm_submission = _paypal_opll_find_submission_attempt(confirm_payload)
    if confirm_submission.get("state") == "failed":
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_confirm",
            "message": f"stripe submission failed: {_paypal_opll_submission_summary(confirm_payload)}",
            "checkout_session_id": cs_id,
            "pm_id": pm_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }

    def poll_for_redirect(timeout: int) -> tuple[str, str]:
        _emit("paypal_extract_poll", message="Polling Stripe payment page for PayPal redirect")
        attempts = max(1, min(60, int(timeout or 30)))
        params = {
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": init_ctx["elements_session_id"],
            "elements_session_client[stripe_js_id]": init_ctx["stripe_js_id"],
            "elements_session_client[locale]": init_ctx.get("locale") or "en",
            "elements_session_client[is_aggregation_expected]": "false",
            "key": stripe_pk,
            "_stripe_version": init_ctx.get("stripe_version") or STRIPE_VERSION_FULL,
        }
        params.update(init_ctx.get("elements_options_client") or {})
        last_summary = ""
        for _attempt in range(attempts):
            if callable(is_cancelled) and is_cancelled():
                break
            try:
                poll_resp = stripe_http.get(
                    f"{STRIPE_API}/v1/payment_pages/{quote(cs_id, safe='')}",
                    params=params,
                    timeout=30,
                )
            except Exception as exc:
                last_summary = str(exc)
                logger.info("[paypal_extract] OPLL payment_page poll failed: %s", exc)
                time.sleep(1.0)
                continue
            if int(getattr(poll_resp, "status_code", 0) or 0) >= 300:
                last_summary = f"HTTP {getattr(poll_resp, 'status_code', '?')}: {str(getattr(poll_resp, 'text', '') or '')[:240]}"
                time.sleep(1.0)
                continue
            payload = _response_json(poll_resp, "paypal_extract_poll")
            redirect = _paypal_opll_redirect_from_payload(payload)
            if redirect:
                return redirect, last_summary
            submission = _paypal_opll_find_submission_attempt(payload)
            if submission.get("state") == "requires_approval":
                raise _PayPalOpllRequiresApproval("payment page requires ChatGPT approval")
            if submission.get("state") == "failed":
                raise RuntimeError(f"stripe submission failed: {_paypal_opll_submission_summary(payload)}")
            last_summary = _paypal_opll_submission_summary(payload)
            time.sleep(1.0)
        return "", last_summary

    def approve_checkout() -> dict[str, Any]:
        _emit("paypal_extract_approve", message="Approving checkout on ChatGPT")
        approve_proxy = "" if mode == "gb" else str(approve_proxy_url or "").strip()
        if approve_proxy and approve_proxy != str(proxy_url or "").strip():
            try:
                http.proxies = {"http": approve_proxy, "https": approve_proxy}
            except Exception:
                logger.debug("[paypal_extract] failed to switch approve proxy", exc_info=True)
        try:
            http.get(
                "https://chatgpt.com/backend-api/sentinel/ping",
                headers={"Referer": "https://chatgpt.com/", "x-openai-target-path": "/backend-api/sentinel/ping"},
                timeout=30,
            )
        except Exception as exc:
            logger.info("[paypal_extract] OPLL sentinel ping before approve soft-failed: %s", exc)
        headers = {
            "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/approve",
            "x-openai-target-route": "/backend-api/payments/checkout/approve",
        }
        resp = http.post(
            "https://chatgpt.com/backend-api/payments/checkout/approve",
            json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
            headers=headers,
            timeout=30,
        )
        if int(getattr(resp, "status_code", 0) or 0) >= 300:
            raise GoPayFlowError(
                f"ChatGPT approve 失败: HTTP {resp.status_code} {str(getattr(resp, 'text', '') or '')[:500]}",
                stage="chatgpt_approve",
            )
        payload = _response_json(resp, "paypal_chatgpt_approve")
        result = str(payload.get("result") or "").strip().lower()
        if result and result != "approved":
            raise GoPayFlowError(f"ChatGPT approve 未通过: {payload}", stage="chatgpt_approve")
        return payload

    try:
        if confirm_submission.get("state") == "requires_approval":
            raise _PayPalOpllRequiresApproval("payment page requires ChatGPT approval")
        redirect_url, last_poll = poll_for_redirect(int(timeout_seconds or 30))
    except _PayPalOpllRequiresApproval:
        try:
            approve_checkout()
            redirect_url, last_poll = poll_for_redirect(max(30, int(timeout_seconds or 30)))
        except Exception as exc:
            return {
                "status": "failed",
                "failure_stage": "extract_ba_link_approve_blocked"
                if "blocked" in str(exc).lower()
                else "extract_ba_link_approve",
                "message": "ChatGPT approve blocked" if "blocked" in str(exc).lower() else str(exc),
                "checkout_session_id": cs_id,
                "pm_id": pm_id,
                "checkout_url": hosted_checkout_url,
                "hosted_checkout_url": hosted_checkout_url,
                "paypal_ba_mode": mode,
            }
    except Exception as exc:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_poll",
            "message": str(exc),
            "checkout_session_id": cs_id,
            "pm_id": pm_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }

    if not redirect_url:
        return {
            "status": "failed",
            "failure_stage": "extract_ba_link_poll",
            "message": f"PayPal redirect not found after OPLL poll; last_poll={last_poll or '-'}",
            "checkout_session_id": cs_id,
            "pm_id": pm_id,
            "checkout_url": hosted_checkout_url,
            "hosted_checkout_url": hosted_checkout_url,
            "paypal_ba_mode": mode,
        }
    return result_from_redirect(redirect_url)


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
    return payment_checkout_browser_service.run_paypal_auto_flow_sequence(
        api,
        email=email,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_credentials=paypal_credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        billing_payload=billing_payload,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
        page_url=lambda: getattr(api.page, "url", ""),
        resolve_checkout_billing_payload=_resolve_checkout_billing_payload,
        normalize_paypal_country=_normalize_paypal_country,
        normalize_paypal_lang=_normalize_paypal_lang,
        progress_adapter=_progress_adapter,
        handle_checkout_handoff=_handle_paypal_auto_flow_checkout_handoff,
        run_paypal_authorize_flow=_run_paypal_authorize_flow,
        paypal_authorize_timeout_seconds=_paypal_authorize_timeout_seconds,
        wait_for_paypal_result=_wait_for_paypal_result,
        paypal_result_timeout_seconds=_paypal_result_timeout_seconds,
        on_progress=on_progress,
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
    pre_extracted: dict[str, Any] | None = None,
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []
    runtime_options = _normalize_paypal_bind_task_runtime_options(
        manual_confirm=manual_confirm,
        paypal_mode=paypal_mode,
        paypal_browser=paypal_browser,
        paypal_fallback_browser=paypal_fallback_browser,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
    )
    auto_mode = bool(runtime_options["auto_mode"])
    paypal_mode = str(runtime_options["paypal_mode"])
    paypal_browser = str(runtime_options["paypal_browser"])
    paypal_fallback_browser = str(runtime_options["paypal_fallback_browser"])
    paypal_country = str(runtime_options["paypal_country"])
    paypal_lang = str(runtime_options["paypal_lang"])
    protocol_mode = bool(runtime_options["protocol_mode"])
    use_camoufox = bool(runtime_options["use_camoufox"])
    use_roxybrowser = bool(runtime_options["use_roxybrowser"])
    browser_fallback_enabled = bool(runtime_options["browser_fallback_enabled"])
    fallback_use_roxybrowser = bool(runtime_options["fallback_use_roxybrowser"])
    fallback_use_camoufox = bool(runtime_options["fallback_use_camoufox"])
    launch_proxy_url = runtime_options["launch_proxy_url"]
    launch_proxy_bypass = runtime_options["launch_proxy_bypass"]
    roxybrowser_workspace_id = str(runtime_options["roxybrowser_workspace_id"])
    roxybrowser_profile_id = str(runtime_options["roxybrowser_profile_id"])

    try:
        protocol_result = _handle_paypal_protocol_mode_dispatch(
            api,
            protocol_mode=protocol_mode,
            pre_extracted=pre_extracted,
            email=email,
            checkout_url=checkout_url,
            proxy_url=launch_proxy_url,
            proxy_bypass=launch_proxy_bypass,
            paypal_mode=paypal_mode,
            paypal_country=paypal_country,
            paypal_lang=paypal_lang,
            paypal_email=paypal_email,
            paypal_password=paypal_password,
            sms_url=sms_url,
            otp_channel=otp_channel,
            paypal_card_number=paypal_card_number,
            paypal_card_expiry=paypal_card_expiry,
            paypal_card_cvv=paypal_card_cvv,
            phone_accounts=phone_accounts,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            fallback_use_camoufox=fallback_use_camoufox,
            fallback_use_roxybrowser=fallback_use_roxybrowser,
            browser_fallback_enabled=browser_fallback_enabled,
            roxybrowser_workspace_id=roxybrowser_workspace_id,
            roxybrowser_profile_id=roxybrowser_profile_id,
            is_cancelled=is_cancelled,
            autofill_enabled=autofill_enabled,
            autofill_payload=autofill_payload,
            on_progress=on_progress,
        )
        if protocol_result is not None:
            return protocol_result

        _launch_paypal_checkout_browser(
            api,
            proxy_url=launch_proxy_url,
            proxy_bypass=launch_proxy_bypass,
            use_fallback_browser=False,
            paypal_country=paypal_country,
            paypal_lang=paypal_lang,
            use_camoufox=use_camoufox,
            use_roxybrowser=use_roxybrowser,
            fallback_use_camoufox=fallback_use_camoufox,
            fallback_use_roxybrowser=fallback_use_roxybrowser,
            roxybrowser_workspace_id=roxybrowser_workspace_id,
            roxybrowser_profile_id=roxybrowser_profile_id,
            on_progress=on_progress,
        )

        checkout_context_result = _handle_paypal_checkout_context_dispatch(
            api,
            email=email,
            checkout_url=checkout_url,
            proxy_url=launch_proxy_url,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
        if checkout_context_result:
            return checkout_context_result

        return _handle_paypal_post_checkout_flow_dispatch(
            api,
            auto_mode=auto_mode,
            email=email,
            checkout_url=checkout_url,
            proxy_url=launch_proxy_url,
            paypal_mode=paypal_mode,
            paypal_country=paypal_country,
            paypal_lang=paypal_lang,
            paypal_email=paypal_email,
            paypal_password=paypal_password,
            sms_url=sms_url,
            otp_channel=otp_channel,
            paypal_card_number=paypal_card_number,
            paypal_card_expiry=paypal_card_expiry,
            paypal_card_cvv=paypal_card_cvv,
            phone_accounts=phone_accounts,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=timeout_seconds,
            is_cancelled=is_cancelled,
            autofill_enabled=autofill_enabled,
            autofill_payload=autofill_payload,
            on_progress=on_progress,
        )
    except Exception as exc:
        return _handle_paypal_unexpected_error(
            api,
            exc,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
        )
    finally:
        _stop_paypal_api_safely(api)
