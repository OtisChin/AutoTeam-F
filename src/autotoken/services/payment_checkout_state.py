"""Shared checkout page state detection helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from autotoken.services import payment_results as payment_results_service

BodyExcerpt = Callable[[Any, int], str]

CHECKOUT_ERROR_PATTERNS = (
    re.compile(r"付款.*未获批准"),
    re.compile(r"未获批准"),
    re.compile(r"出了错"),
    re.compile(r"请重试"),
    re.compile(r"payment.*not.*approved", re.IGNORECASE),
    re.compile(r"payment.*declined", re.IGNORECASE),
    re.compile(r"not.*approved", re.IGNORECASE),
    re.compile(r"try again", re.IGNORECASE),
    re.compile(r"something went wrong", re.IGNORECASE),
    re.compile(r"unable to process", re.IGNORECASE),
    re.compile(r"customer'?s location.*(?:not|isn'?t).*recognized", re.IGNORECASE),
    re.compile(r"valid customer address", re.IGNORECASE),
    re.compile(r"automatically calculate tax", re.IGNORECASE),
    re.compile(r"http\s*429", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"请求.*(?:过多|频繁)"),
)

CHECKOUT_PAYMENT_NOT_APPROVED_PATTERNS = (
    re.compile(r"付款.*未获批准"),
    re.compile(r"未获批准"),
    re.compile(r"payment\s+(?:was\s+)?not\s+approved", re.IGNORECASE),
    re.compile(r"payment\s+(?:was\s+)?declined", re.IGNORECASE),
    re.compile(r"not\s+approved", re.IGNORECASE),
)

PAYPAL_SUCCESS_HINTS = (
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
PAYPAL_FAILURE_HINTS = (
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
PAYPAL_PENDING_HINTS = (
    "payment pending",
    "processing payment",
    "we're processing",
    "正在处理",
    "处理中",
)
PAYPAL_CANCEL_HINTS = (
    "payment canceled",
    "payment cancelled",
    "checkout canceled",
    "checkout cancelled",
    "you cancelled",
    "取消付款",
)
PAYPAL_REVIEW_HINTS = (
    "authentication required",
    "verify your purchase",
    "complete the verification",
    "return to merchant",
    "需要验证",
    "请完成验证",
    "3d secure",
)
PAYPAL_SUCCESS_URL_RE = re.compile(r"(?:success|complete|completed|thank|subscribed)", re.I)
PAYPAL_FAILURE_URL_RE = re.compile(r"(?:failed|failure|declined|error)", re.I)
PAYPAL_CANCEL_URL_RE = re.compile(r"(?:cancel|cancelled|canceled)", re.I)
PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS = 180
PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS = 300
PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS = 120
PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS = 180
DATADOME_SLIDER_KEYWORDS = (
    "将滑块",
    "确认您是人类",
    "Slide the puzzle",
    "move the slider",
    "Move the slider",
    "滑动到最右",
    "Slide to continue",
    "slide to verify",
)
DATADOME_BLOCKED_KEYWORDS = (
    "You have been blocked",
    "you have been blocked",
    "Access denied",
    "access denied",
    "Your request has been blocked",
    "请求已被拦截",
    "您的访问已被阻止",
)
DATADOME_FRAME_URL_HINTS = (
    "datadome",
    "captcha-delivery.com",
    "geo.captcha-delivery.com",
    "ddc.paypal.com",
    "geo.ddc.paypal.com",
)


def bounded_timeout_seconds(value: int | None, *, minimum: int, maximum: int) -> int:
    requested = int(value or 0)
    if requested <= 0:
        return minimum
    return max(minimum, min(requested, maximum))


def paypal_authorize_timeout_seconds(timeout_seconds: int | None) -> int:
    return bounded_timeout_seconds(
        timeout_seconds,
        minimum=PAYPAL_AUTO_AUTHORIZE_MIN_TIMEOUT_SECONDS,
        maximum=PAYPAL_AUTO_AUTHORIZE_MAX_TIMEOUT_SECONDS,
    )


def paypal_result_timeout_seconds(timeout_seconds: int | None) -> int:
    return bounded_timeout_seconds(
        timeout_seconds,
        minimum=PAYPAL_AUTO_RESULT_MIN_TIMEOUT_SECONDS,
        maximum=PAYPAL_AUTO_RESULT_MAX_TIMEOUT_SECONDS,
    )


def datadome_blocked_text_hint(text: str) -> bool:
    raw = str(text or "")
    return any(keyword in raw for keyword in DATADOME_BLOCKED_KEYWORDS)


def datadome_slider_text_hint(text: str) -> bool:
    raw = str(text or "")
    return any(keyword in raw for keyword in DATADOME_SLIDER_KEYWORDS)


def is_datadome_frame_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(hint in lowered for hint in DATADOME_FRAME_URL_HINTS)


def paypal_signup_otp_text_hint(text: str, *, loose: bool = False) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    simple_hints = (
        "enter your code",
        "we sent a 6-digit code",
        "sent a 6-digit code",
        "6-digit code",
        "verification code",
        "コードを入力",
        "確認コード",
        "認証コード",
        "6桁のコード",
    )
    if loose:
        simple_hints = (
            *simple_hints,
            "enter the code",
            "enter code",
            "code was sent",
            "check your phone",
            "验证码",
        )
    if any(hint in lowered for hint in simple_hints):
        return True
    if "security code" in lowered and any(hint in lowered for hint in ("enter", "sent", "verification", "phone")):
        return True
    return "セキュリティコード" in raw and any(
        hint in raw for hint in ("コードを入力", "送信しました", "6桁", "確認", "認証")
    )


def paypal_signup_otp_entry_text_hint(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        hint in lowered
        for hint in (
            "enter your code",
            "6-digit code",
            "verification code",
            "security code",
            "コードを入力",
            "セキュリティコード",
            "確認コード",
            "認証コード",
            "6桁のコード",
        )
    )


def paypal_signup_registration_text_hint(text: str) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    return (
        ("card number" in lowered and "billing address" in lowered)
        or ("create password" in lowered and "agree & create account" in lowered)
        or ("pay with debit or credit card" in lowered and "create password" in lowered)
        or ("カード番号" in raw and "請求先住所" in raw)
        or ("電話番号" in raw and "パスワードの作成" in raw)
        or ("生年月日" in raw and "同意して続行" in raw)
    )


def paypal_signup_registration_form_text_visible(text: str) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    ascii_markers = (
        "card number",
        "billing address",
        "create password",
        "agree & create account",
    )
    jp_markers = (
        "カード番号",
        "請求先住所",
        "電話番号",
        "パスワードの作成",
        "生年月日",
        "同意して続行",
        "都道府県",
        "郵便番号",
    )
    marker_count = sum(1 for marker in ascii_markers if marker in lowered)
    marker_count += sum(1 for marker in jp_markers if marker in raw)
    return marker_count >= 2


def paypal_login_text_hint(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        hint in lowered
        for hint in (
            "log in",
            "login",
            "sign in",
            "welcome back",
            "password",
            "邮箱",
            "登录",
        )
    )


def paypal_passkey_text_hint(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        hint in lowered
        for hint in (
            "passkey",
            "security key",
            "try another way",
            "use password instead",
            "通行密钥",
            "改用密码",
        )
    )


def paypal_approve_text_hint(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        hint in lowered
        for hint in (
            "agree and continue",
            "authorize",
            "consent",
            "accept",
            "同意并继续",
            "授权",
        )
    )


def text_matches_any_hint(text: str, hints: tuple[str, ...] | list[str]) -> bool:
    lowered = str(text or "").lower()
    return bool(lowered) and any(str(hint or "").lower() in lowered for hint in hints)


def paypal_phone_rejected_text_hint(text: str, *, hints: tuple[str, ...] | list[str]) -> bool:
    return text_matches_any_hint(text, hints)


def paypal_card_rejected_text_hint(text: str, *, hints: tuple[str, ...] | list[str]) -> bool:
    return text_matches_any_hint(text, hints)


def parse_display_amount(value: Any) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"(?i)\b(?:idr|rp|usd)\b|us\$|\$", "", raw)
    cleaned = re.sub(r"[^\d,.\-+]", "", cleaned)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        normalized = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        normalized = "".join(parts) if all(len(part) == 3 for part in parts[1:]) else cleaned.replace(",", ".")
    else:
        normalized = cleaned
    try:
        return int(float(normalized))
    except Exception:
        return None


def is_checkout_payment_not_approved_error(text: str) -> bool:
    clean = str(text or "").strip()
    return bool(clean and any(pattern.search(clean) for pattern in CHECKOUT_PAYMENT_NOT_APPROVED_PATTERNS))


def is_checkout_customer_location_error(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    return bool(
        re.search(r"customer'?s location.*(?:not|isn'?t).*recognized", clean, re.IGNORECASE)
        or re.search(r"valid customer address", clean, re.IGNORECASE)
        or re.search(r"automatically calculate tax", clean, re.IGNORECASE)
    )


def is_checkout_rate_limited_error(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    return "429" in clean or payment_results_service.looks_like_gopay_rate_limit_text(clean)


def is_checkout_payment_not_approved_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    stage = str(result.get("failure_stage") or "")
    if stage not in {"checkout_not_approved", "browser_checkout", "submit_checkout"}:
        return False
    return is_checkout_payment_not_approved_error(str(result.get("message") or ""))


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

    if PAYPAL_CANCEL_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in PAYPAL_CANCEL_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付已取消",
        }

    if (
        stripe_return_success
        or chatgpt_success
        or redirect_status in {"succeeded", "success", "complete", "completed"}
        or "setup_intent=" in normalized_url
        and "redirect_pm_type=paypal" in normalized_url
        or PAYPAL_SUCCESS_URL_RE.search(parsed_url.path)
        or any(hint in haystack for hint in PAYPAL_SUCCESS_HINTS)
    ):
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到 PayPal/支付成功页面",
        }

    if PAYPAL_FAILURE_URL_RE.search(parsed_url.path) or any(hint in haystack for hint in PAYPAL_FAILURE_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal/支付失败提示",
        }

    if any(hint in haystack for hint in PAYPAL_PENDING_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": "检测到 PayPal 支付处理中，需要人工确认最终状态",
        }

    if any(hint in haystack for hint in PAYPAL_REVIEW_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": "检测到需要额外验证或人工确认",
        }

    return None


def classify_paypal_stripe_payment_page(payload: dict[str, Any] | None):
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


def paypal_risk_challenge_text_hint(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(lowered) and any(
        hint in lowered for hint in PAYPAL_DATADOME_BLOCKED_HINTS + PAYPAL_HUMAN_VERIFICATION_HINTS
    )


def safe_host(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def is_paypal_host(url: str) -> bool:
    host = safe_host(url)
    return host == "paypal.com" or host.endswith(".paypal.com")


def is_paypal_ssl_protocol_error_page(url: str, body_text: str = "") -> bool:
    text = f"{url}\n{body_text}".lower()
    if not is_paypal_host(url) and "paypal.com" not in text:
        return False
    return (
        "err_ssl_protocol_error" in text
        or "sent an invalid response" in text
        or "can't provide a secure connection" in text
        or "cannot provide a secure connection" in text
        or ("this site" in text and "secure connection" in text and "paypal.com" in text)
    )


def is_checkout_host(url: str) -> bool:
    host = safe_host(url)
    if host in {"pay.openai.com", "checkout.stripe.com"}:
        return True
    return host == "chatgpt.com" and "/checkout/" in str(url or "").lower()


def is_chatgpt_or_openai_return_url(url: str) -> bool:
    host = safe_host(url)
    return host == "chatgpt.com" or host == "openai.com" or host.endswith(".openai.com")


def paypal_autofill_allowed(url: str) -> bool:
    host = safe_host(url)
    if not host or is_paypal_host(url):
        return False
    return host in {"pay.openai.com", "checkout.stripe.com", "chatgpt.com"} or host.endswith(".stripe.com")


def is_paypal_pay_entry_url(url: str) -> bool:
    try:
        parsed = urlsplit(str(url or ""))
    except Exception:
        return False
    return is_paypal_host(url) and parsed.path.rstrip("/").lower() == "/pay"


def paypal_protocol_transient_transport_error(message: str) -> bool:
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


def paypal_protocol_needs_browser_fallback(result: dict) -> bool:
    if result.get("status") == "success":
        return False
    stage = str(result.get("failure_stage") or "")
    has_fallback_target = bool(result.get("paypal_approve_url") or result.get("ba_token"))
    if stage in {"paypal_human_verification", "paypal_protocol_authorize"}:
        return has_fallback_target
    if stage == "paypal_protocol" and has_fallback_target:
        return paypal_protocol_transient_transport_error(str(result.get("message") or ""))
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


def compact_checkout_error(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    for phrase in ("付款未获批准", "出了错，请重试。", "出错了，请重试。", "请重试。"):
        if phrase in clean:
            return phrase
    english_patterns = (
        r"the customer'?s location isn'?t recognized[^.。]*\.?",
        r"set a valid customer address[^.。]*\.?",
        r"automatically calculate tax[^.。]*\.?",
        r"payment\s+(?:was\s+)?not\s+approved",
        r"payment\s+(?:was\s+)?declined",
        r"something went wrong",
        r"please try again",
        r"try again",
        r"unable to process[^.。]*",
    )
    for pattern in english_patterns:
        matched = re.search(pattern, clean, flags=re.IGNORECASE)
        if matched:
            return matched.group(0).strip()
    return clean[:500]


def extract_checkout_error(api: Any, *, body_excerpt: BodyExcerpt) -> str:
    script = """() => {
      const isVisible = (node) => {
        if (!node || !node.getBoundingClientRect) return false;
        const style = window.getComputedStyle(node);
        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const nodes = Array.from(document.querySelectorAll('[role="alert"],[aria-live],div,span,p'));
      return nodes
        .filter(isVisible)
        .map((node) => (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim())
        .filter(Boolean)
        .slice(0, 300);
    }"""
    try:
        candidates = api.page.evaluate(script) or []
    except Exception:
        candidates = []
    matched_errors = []
    for text in candidates:
        clean = str(text or "").strip()
        if not clean:
            continue
        if any(pattern.search(clean) for pattern in CHECKOUT_ERROR_PATTERNS):
            matched_errors.append(compact_checkout_error(clean))
    if matched_errors:
        return sorted(matched_errors, key=len)[0]

    body = body_excerpt(api, 2000)
    matched_errors = []
    for line in re.split(r"[\r\n]+", body):
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and any(pattern.search(clean) for pattern in CHECKOUT_ERROR_PATTERNS):
            matched_errors.append(compact_checkout_error(clean))
    if matched_errors:
        return sorted(matched_errors, key=len)[0]
    return ""


def checkout_nonzero_amount_hint_from_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    amount_expr = r"(?:IDR|Rp|US\$|\$)\s*[-+]?\d[\d,.]*(?:\.\d{1,2})?|[-+]?\d[\d,.]*(?:\.\d{1,2})?\s*(?:IDR|Rp|USD)"
    today_patterns = (
        rf"(?:今日应付合计|今天应付合计|今日应付|今天应付|今日支付合计|今天支付合计|应付金额|支付金额|amount\s+due|total\s+due\s+today|due\s+today|today'?s\s+total|total\s+payment|payment\s+total|jumlah\s+yang\s+harus\s+dibayar|total\s+pembayaran)\s*({amount_expr})",
        rf"({amount_expr})\s*(?:total\s+due\s+today|due\s+today|today'?s\s+total|total\s+payment|payment\s+total|今日应付合计|今天应付合计|今日应付|今天应付|今日支付合计|今天支付合计|应付金额|支付金额|jumlah\s+yang\s+harus\s+dibayar|total\s+pembayaran)",
    )
    for pattern in today_patterns:
        matched = re.search(pattern, compact, flags=re.IGNORECASE)
        if not matched:
            continue
        amount_text = matched.group(1).strip()
        parsed = parse_display_amount(amount_text)
        if parsed and parsed > 0:
            return amount_text
        return ""
    zero_markers = (
        "$0",
        "us$0",
        "idr 0",
        "rp0",
        "rp 0",
        "free trial",
        "free today",
        "gratis",
        "免费",
        "0.00",
    )
    lower = compact.lower()
    if any(marker in lower for marker in zero_markers):
        return ""
    amount_patterns = (
        r"(?:us\$|\$)\s*(?:[1-9]\d*)(?:[.,]\d{2})?",
        r"(?:idr|rp)\s*[1-9]\d*(?:[.,]\d{3})*(?:\.\d{1,2})?",
        r"[1-9]\d*(?:[.,]\d{3})*(?:\.\d{1,2})?\s*(?:idr|rp)",
    )
    for pattern in amount_patterns:
        matched = re.search(pattern, compact, flags=re.IGNORECASE)
        if matched:
            return matched.group(0)
    return ""


def browser_checkout_nonzero_amount_hint(api: Any, *, body_excerpt: BodyExcerpt) -> str:
    return checkout_nonzero_amount_hint_from_text(body_excerpt(api, 3500))
