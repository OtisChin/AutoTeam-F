"""Payment task result classifiers and retry helpers."""

import json
import re
from typing import Any

from autotoken.core.normalization import normalized_email


def _normalized_email(value: Any) -> str:
    return normalized_email(value)


def is_bind_card_reusable_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    return result.get("status") == "failed" and result.get("failure_stage") in {"open_checkout", "fill_card"}


def is_gopay_checkout_not_approved_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    stage = str(result.get("failure_stage") or "")
    if stage not in {"checkout_not_approved", "browser_checkout", "submit_checkout"}:
        return False
    message = str(result.get("message") or "")
    return bool(
        re.search(r"付款.*未获批准|未获批准", message)
        or re.search(r"payment\s+(?:was\s+)?not\s+approved|payment\s+(?:was\s+)?declined|not\s+approved", message, re.I)
    )


def gopay_rejected_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("rejected_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if is_gopay_checkout_not_approved_result(result):
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def gopay_nonzero_blocked_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("nonzero_blocked_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if str(result.get("failure_stage") or "") in {
        "browser_charge_guard",
        "stripe_charge_guard",
        "midtrans_charge_guard",
    }:
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def gopay_payment_failed_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("payment_failed_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    if str(result.get("failure_stage") or "") == "gopay_payment_process":
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def gopay_token_invalidated_pool_emails(result: dict, actual_email: str) -> list[str]:
    seen = set()
    emails = []
    for raw_email in result.get("token_invalidated_emails") or []:
        email = _normalized_email(raw_email)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    message = str(result.get("message") or "").lower()
    if result.get("status") != "success" and (
        "token_invalidated" in message
        or "authentication token has been invalidated" in message
        or ("http 401" in message and "invalidated" in message)
    ):
        email = _normalized_email(actual_email)
        if email and email not in seen:
            emails.append(email)
    return emails


def looks_like_gopay_rate_limit_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "请求过多",
            "请求太多",
            "尝试过多",
            "请求频繁",
            "操作过于频繁",
            "访问过于频繁",
            "请稍后重试",
            "请稍后再试",
            "稍后再试",
            "稍后重试",
            "更换 gopay",
            "更换 gopay 手机号",
            "更换 gopay 手机号/钱包",
            "too many attempts",
            "too many requests",
            "rate limited",
            "rate limit",
            "try again later",
            "please try again later",
            "terlalu banyak",
            "terlalu banyak permintaan",
            "terlalu banyak percobaan",
            "permintaan terlalu banyak",
            "terlalu sering",
            "anda sudah mencoba terlalu banyak",
            "kamu sudah mencoba terlalu banyak",
            "kamu udah kebanyakan nyoba",
            "udah kebanyakan nyoba",
            "kebanyakan nyoba",
            "kebanyakan mencoba",
            "sudah terlalu banyak mencoba",
            "coba lagi setelah beberapa saat",
            "setelah beberapa saat",
            "coba lagi nanti",
            "coba beberapa saat lagi",
            "silakan coba lagi nanti",
            "silahkan coba lagi nanti",
            "mohon coba lagi nanti",
        )
    )


def looks_like_http_forbidden_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return "http 403" in normalized or "status 403" in normalized or "forbidden" in normalized


def looks_like_chatgpt_user_paid_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "user is paid",
            "user already paid",
            "already a paid user",
            "already paid user",
            "already subscribed",
            "already has an active subscription",
            "用户已付费",
            "已是付费用户",
            "已有有效订阅",
        )
    )


def is_chatgpt_user_paid_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return bool(result.get("user_paid_skip"))
    return looks_like_chatgpt_user_paid_text(json.dumps(result, ensure_ascii=False))


def chatgpt_user_paid_success(
    result: dict | None,
    *,
    checkout_url: str = "",
    billing_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(result or {})
    payload.update(
        {
            "status": "success",
            "failure_stage": "",
            "message": "ChatGPT 返回 user is paid，账号已是付费用户，跳过 GoPay 绑卡",
            "user_paid_skip": True,
        }
    )
    if checkout_url and not payload.get("checkout_url"):
        payload["checkout_url"] = checkout_url
    if billing_info and not payload.get("billing_info"):
        payload["billing_info"] = billing_info
    return payload


def is_chatgpt_token_invalidated_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    text = json.dumps(result, ensure_ascii=False).lower()
    return (
        "token_invalidated" in text
        or "token_revoked" in text
        or "invalidated oauth token" in text
        or "authentication token has been invalidated" in text
        or ("http 401" in text and "invalidated" in text)
    )


def is_chatgpt_approve_blocked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("failure_stage") or "") != "chatgpt_approve":
        return False
    return "blocked" in str(result.get("message") or "").lower()


def chatgpt_approve_blocked_message(payload: dict) -> str:
    return (
        f"ChatGPT approve 未通过: {payload}；"
        "这发生在 GoPay/Midtrans 前，表示 ChatGPT checkout approve 被风控拦截。"
        "浏览器能打开 checkout 页不等于协议 approve 会通过。"
        "可等待账号冷却、切换 auth_session，或在浏览器手动选择 GoPay 后把 "
        "pm-redirects.stripe.com / app.midtrans.com/snap 链接粘到 Checkout 链接继续接管 GoPay"
    )


def is_gopay_payment_process_rotatable_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    if str(result.get("failure_stage") or "") != "gopay_payment_process":
        return False
    message = str(result.get("message") or "").lower()
    return (
        "gopay_wallet" in message
        or "payment-switch" in message
        or "createauth" in message
        or "errorcode=201" in message
        or '"code":"201"' in message
        or "'code': '201'" in message
        or "transaction is denied" in message
        or "try another payment method" in message
        or "transaction_status" in message
        and "deny" in message
        or "fraud_status" in message
        and "deny" in message
    )


def is_gopay_nonzero_amount_blocked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    return str(result.get("failure_stage") or "") in {
        "browser_charge_guard",
        "stripe_charge_guard",
        "midtrans_charge_guard",
    }


def is_gopay_already_linked_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    message = str(result.get("message") or "").lower()
    return str(result.get("failure_stage") or "") == "midtrans_linking" and (
        "already linked" in message or "已绑定其他账号" in message or "绑定其他账号" in message
    )


def is_midtrans_linking_rate_limited_result(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "success":
        return False
    return (
        str(result.get("failure_stage") or "") == "midtrans_linking"
        and "http 429" in str(result.get("message") or "").lower()
    )


def gopay_pending_retry_reason(result: dict | None) -> str:
    if not isinstance(result, dict) or result.get("status") == "success":
        return ""
    if (
        is_chatgpt_user_paid_result(result)
        or is_chatgpt_token_invalidated_result(result)
        or is_gopay_nonzero_amount_blocked_result(result)
    ):
        return ""
    if is_chatgpt_approve_blocked_result(result):
        return "chatgpt_approve_blocked"
    if is_gopay_payment_process_rotatable_result(result):
        return "gopay_payment_process"
    if is_gopay_already_linked_result(result):
        return "gopay_already_linked"
    stage = str(result.get("failure_stage") or "")
    message = str(result.get("message") or "")
    if (
        is_midtrans_linking_rate_limited_result(result)
        or stage == "gopay_rate_limited"
        or looks_like_gopay_rate_limit_text(message)
    ):
        return "rate_limited"
    if stage == "gopay_wallet_no_numbers" or "no_numbers" in message.lower() or "no numbers" in message.lower():
        return "gopay_wallet_no_numbers"
    if stage in {"fetch_otp", "gopay_validate_otp", "trigger_sms_otp"}:
        return "gopay_otp"
    if looks_like_http_forbidden_text(message):
        return "http_403"
    if stage in {
        "resolve_midtrans_redirect",
        "pm_redirect",
        "midtrans_load_transaction",
        "midtrans_linking",
        "gopay_validate_reference",
        "gopay_user_consent",
        "gopay_payment_validate",
        "gopay_payment_confirm",
        "browser_checkout",
        "generate_checkout",
        "chatgpt_http_session",
        "chatgpt_verify",
        "chatgpt_approve",
    }:
        return "transient_gopay_flow"
    return ""


def gopay_pending_retry_source_stage(_result: dict | None, reason: str) -> str:
    if reason == "checkout_not_approved":
        return "checkout_not_approved_rotate"
    if reason == "gopay_payment_process":
        return "gopay_payment_process_failed_rotate"
    if reason == "gopay_already_linked":
        return "gopay_already_linked_retry"
    if reason == "rate_limited":
        return "gopay_rate_limited_retry"
    if reason == "gopay_wallet_no_numbers":
        return "gopay_wallet_no_numbers_retry"
    if reason == "gopay_otp":
        return "gopay_otp_retry"
    return "gopay_retryable_failure_rotate"
