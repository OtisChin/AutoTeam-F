"""Account overview, access token, and ChatGPT subscription HTTP routes."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

CHATGPT_SUBSCRIPTIONS_PATH = "/backend-api/subscriptions"
CHATGPT_SUBSCRIPTIONS_URL = f"https://chatgpt.com{CHATGPT_SUBSCRIPTIONS_PATH}"
CHATGPT_SUBSCRIPTIONS_FALLBACK_URL = f"https://chat.openai.com{CHATGPT_SUBSCRIPTIONS_PATH}"
CHATGPT_ACCOUNT_CHECK_PATH = "/backend-api/accounts/check/v4-2023-04-27"
CHATGPT_ACCOUNT_CHECK_URL = f"https://chatgpt.com{CHATGPT_ACCOUNT_CHECK_PATH}"
CHATGPT_ACCOUNT_CHECK_FALLBACK_URL = f"https://chat.openai.com{CHATGPT_ACCOUNT_CHECK_PATH}"
CHATGPT_SUBSCRIPTION_MAX_ATTEMPTS = 3


class ExportAccessTokensParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


def _extract_access_token(auth_data: dict[str, Any]) -> str:
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    return str(
        auth_data.get("access_token", "")
        or auth_data.get("accessToken", "")
        or auth_data.get("chatgpt_access_token", "")
        or data.get("access_token", "")
        or data.get("accessToken", "")
        or data.get("chatgpt_access_token", "")
        or ""
    ).strip()


def _extract_account_id(auth_data: dict[str, Any]) -> str:
    account = auth_data.get("account") if isinstance(auth_data.get("account"), dict) else {}
    data = auth_data.get("data") if isinstance(auth_data.get("data"), dict) else {}
    data_account = data.get("account") if isinstance(data.get("account"), dict) else {}
    account_id = str(
        auth_data.get("account_id", "")
        or auth_data.get("accountId", "")
        or account.get("id")
        or data.get("account_id", "")
        or data.get("accountId", "")
        or data_account.get("id")
        or ""
    ).strip()
    if account_id:
        return account_id
    access_token = _extract_access_token(auth_data)
    if not access_token:
        return ""
    try:
        from autotoken.core.jwt import decode_jwt_payload

        claims = decode_jwt_payload(access_token)
    except Exception:
        return ""
    auth_claims = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else {}
    if isinstance(auth_claims, dict):
        return str(auth_claims.get("chatgpt_account_id") or "").strip()
    return ""


def _extract_jwt_plan_type(access_token: str) -> str:
    from autotoken.core.jwt import decode_jwt_payload

    try:
        claims = decode_jwt_payload(access_token)
    except Exception:
        return ""
    auth_claims = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else {}
    if isinstance(auth_claims, dict):
        return str(auth_claims.get("chatgpt_plan_type") or "").strip()
    return ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "active", "paid"}
    return bool(value)


def _first_present(mapping: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return default


def _first_chatgpt_account(raw: dict[str, Any], account_id: str = "") -> dict[str, Any]:
    account = raw.get("account")
    if isinstance(account, dict):
        return account
    accounts = raw.get("accounts")
    if isinstance(accounts, dict):
        normalized_account_id = str(account_id or "").strip()
        if normalized_account_id and isinstance(accounts.get(normalized_account_id), dict):
            return accounts[normalized_account_id]
        values = [value for value in accounts.values() if isinstance(value, dict)]
        for value in values:
            if isinstance(value.get("account_plan"), dict) or isinstance(value.get("subscription"), dict):
                return value
        return values[0] if values else {}
    if isinstance(accounts, list):
        for value in accounts:
            if isinstance(value, dict):
                return value
    return {}


def _plan_label(plan_key: str, plan_type: str) -> str:
    normalized_type = str(plan_type or "").strip().lower()
    if normalized_type in {"plus", "pro", "team", "enterprise", "free"}:
        return normalized_type.capitalize()
    normalized_key = str(plan_key or "").strip().lower()
    if "plus" in normalized_key:
        return "Plus"
    if "pro" in normalized_key:
        return "Pro"
    if "team" in normalized_key:
        return "Team"
    if "enterprise" in normalized_key:
        return "Enterprise"
    if "free" in normalized_key:
        return "Free"
    return str(plan_key or plan_type or "Unknown")


def _plan_key(plan_key: str, plan_type: str) -> str:
    normalized_key = str(plan_key or "").strip()
    if normalized_key:
        return normalized_key
    normalized_type = str(plan_type or "").strip().lower()
    if normalized_type in {"free", "plus", "pro", "team", "enterprise"}:
        return f"chatgpt{normalized_type}plan"
    return normalized_type


def _channel_label(origin: str) -> str:
    normalized = str(origin or "").strip().lower()
    if normalized == "chatgpt_web":
        return "网页 (Web)"
    if normalized == "chatgpt_not_purchased":
        return "未购买"
    if normalized == "ios":
        return "iOS"
    if normalized == "android":
        return "Android"
    return origin or "-"


def _coerce_datetime(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return str(value)
    return str(value)


def _remaining_days(ends_at: Any) -> int | None:
    coerced = _coerce_datetime(ends_at)
    if not coerced:
        return None
    try:
        dt = datetime.fromisoformat(str(coerced).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    seconds = (dt - datetime.now(UTC)).total_seconds()
    return max(0, int((seconds + 86399) // 86400))


def _seat_value(plan: dict[str, Any], *keys: str) -> int | None:
    value = _first_present(plan, *keys, default=None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_discount(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": str(_first_present(item, "id", "coupon_id", "promotion_id", "promo_campaign_id", default="")).strip(),
        "percent_off": _first_present(
            item, "percent_off", "percentage_off", "discount_percent", "amount", default=None
        ),
        "duration_in_months": _first_present(
            item, "duration_in_months", "duration_num_periods", "months", default=None
        ),
        "ends_at": _coerce_datetime(
            _first_present(item, "end_date", "discount_expires_at", "ends_at", "term_end", default="")
        ),
        "end_behavior": str(
            _first_present(item, "end_behavior", "cancellation_policy", "ends_when", default="")
        ).strip(),
    }


def normalize_chatgpt_subscription(raw: dict[str, Any], account_id: str = "") -> dict[str, Any]:
    """Normalize ChatGPT subscription responses into UI-friendly fields."""

    wrapped_raw = isinstance(raw.get("subscription"), dict) or isinstance(raw.get("account_check"), dict)
    subscription_raw = raw.get("subscription") if isinstance(raw.get("subscription"), dict) else raw
    account_check_raw = raw.get("account_check") if isinstance(raw.get("account_check"), dict) else {}
    account = _first_chatgpt_account(account_check_raw or raw, account_id=account_id)
    entitlement = account.get("entitlement") if isinstance(account.get("entitlement"), dict) else {}
    account_details = account.get("account") if isinstance(account.get("account"), dict) else {}
    plan = subscription_raw if wrapped_raw and isinstance(subscription_raw, dict) else {}
    if not plan and entitlement:
        plan = entitlement
    if not plan and isinstance(account.get("account_plan"), dict):
        plan = account.get("account_plan") or {}
    if not plan and isinstance(account.get("subscription"), dict):
        plan = account.get("subscription") or {}
    if not plan and isinstance(raw.get("account_plan"), dict):
        plan = raw.get("account_plan") or {}
    if not plan and isinstance(raw.get("subscription"), dict):
        plan = raw.get("subscription") or {}
    if not plan:
        plan = raw

    plan_key = str(_first_present(plan, "subscription_plan", "plan", "plan_key", "product_id", default="")).strip()
    if not plan_key:
        plan_key = str(
            _first_present(entitlement, "subscription_plan", "plan", "plan_key", "product_id", default="")
        ).strip()
    plan_type = str(_first_present(plan, "account_plan_type", "plan_type", "tier", default="")).strip()
    if not plan_type:
        plan_type = str(_first_present(account_details, "plan_type", default="")).strip()
    ends_at = _first_present(
        plan,
        "expires_at",
        "current_period_end",
        "subscription_expires_at",
        "subscription_expires_at_timestamp",
        "current_period_end_timestamp",
        "ends_at",
        default="",
    )
    renews_at = _first_present(
        plan,
        "renewal_at",
        "next_invoice_at",
        "next_billing_date",
        "next_billing_date_timestamp",
        "renews_at",
        default="",
    )
    starts_at = _first_present(plan, "start_date", "started_at", "subscription_started_at", default="")
    if not starts_at:
        starts_at = _first_present(plan, "active_start", default="")
    purchase_origin = str(_first_present(plan, "purchase_origin", "purchase_source", "origin", default="")).strip()

    available_plans = _first_present(plan, "available_plans", default=None)
    if available_plans is None:
        available_plans = _first_present(account, "available_plans", default=[])
    if not available_plans and isinstance(account.get("eligible_offers"), dict):
        offers = account["eligible_offers"].get("offers")
        if isinstance(offers, list):
            available_plans = [
                str(item.get("id") or "").strip() for item in offers if isinstance(item, dict) and item.get("id")
            ]
    if not isinstance(available_plans, list):
        available_plans = []
    total_seats = _seat_value(plan, "total_seats", "seats_entitled", "seats", "quantity", "seat_count", "max_seats")
    used_seats = _seat_value(plan, "used_seats", "seats_in_use", "occupied_seats", "seat_used", "seat_count_used")
    discounts = _first_present(plan, "applied_discounts", "discounts", default=[])
    if not discounts:
        discounts = _first_present(entitlement, "applied_discounts", "discounts", default=[])
    if not discounts and isinstance(entitlement.get("discount"), dict):
        discounts = [entitlement.get("discount")]
    if isinstance(discounts, dict):
        discounts = [discounts]
    if not isinstance(discounts, list):
        discounts = []
    applied_discounts = [normalized for normalized in (_normalize_discount(item) for item in discounts) if normalized]

    if not ends_at:
        ends_at = _first_present(plan, "active_until", default="")
    if not renews_at and _truthy(_first_present(plan, "will_renew", "is_renewing", "auto_renews", default=False)):
        renews_at = ends_at
    normalized_plan_key = _plan_key(plan_key, plan_type)
    active_value = _first_present(
        plan,
        "is_active_subscription",
        "is_paid_subscription_active",
        "has_active_subscription",
        "active",
        "has_paid_subscription",
        default=None,
    )
    if active_value is None and ends_at:
        active_value = _remaining_days(ends_at) is not None and (_remaining_days(ends_at) or 0) > 0
    payment_processor = str(_first_present(plan, "payment_processor", "processor", "provider", default="")).strip()
    if not payment_processor and _truthy(_first_present(plan, "is_processor_stripe", default=False)):
        payment_processor = "Stripe"
    channel_label = _channel_label(purchase_origin)
    if channel_label == "-" and isinstance(account.get("last_active_subscription"), dict):
        purchase_origin = str(
            _first_present(account["last_active_subscription"], "purchase_origin_platform", default="")
        ).strip()
        channel_label = _channel_label(purchase_origin)
    if channel_label == "-" and payment_processor:
        channel_label = "网页 (Web)"

    return {
        "plan_label": _plan_label(plan_key, plan_type),
        "plan_key": normalized_plan_key,
        "plan_type": plan_type,
        "billing_period": str(
            _first_present(plan, "billing_period", "scheduled_billing_period", "billing_cycle", "interval", default="")
        ).strip(),
        "currency": str(_first_present(plan, "currency", "billing_currency", "currency_code", default="")).strip(),
        "active": _truthy(active_value),
        "renewing": _truthy(_first_present(plan, "is_renewing", "will_renew", "auto_renews", default=False)),
        "delinquent": _truthy(_first_present(plan, "is_delinquent", "delinquent", "past_due", default=False)),
        "paid": _truthy(
            _first_present(
                plan,
                "has_paid_subscription",
                "has_had_paid_subscription",
                "is_paid",
                default=_truthy(account_details.get("has_previously_paid_subscription"))
                or str(plan_type).strip().lower() not in {"", "free"},
            )
        ),
        "starts_at": _coerce_datetime(starts_at),
        "ends_at": _coerce_datetime(ends_at),
        "renews_at": _coerce_datetime(renews_at),
        "purchase_origin": purchase_origin,
        "channel_label": channel_label,
        "payment_processor": payment_processor,
        "seats": {"used": used_seats, "total": total_seats},
        "available_plans": available_plans,
        "discount": _first_present(plan, "discount", "discount_amount", "discount_percent", default=None),
        "applied_discounts": applied_discounts,
        "remaining_days": _remaining_days(ends_at),
    }


def _browser_timezone_offset_min() -> int:
    import time

    local_utc_offset_seconds = -time.timezone
    if time.daylight and time.localtime().tm_isdst > 0:
        local_utc_offset_seconds = -time.altzone
    return int(-local_utc_offset_seconds / 60)


def _new_chatgpt_subscription_session(access_token: str, proxy_url: str = ""):
    try:
        from autotoken.payments.us_paypal import build_chatgpt_session

        return build_chatgpt_session(access_token, proxy_url=proxy_url)
    except Exception:
        import requests

        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "*/*",
                "User-Agent": "Mozilla/5.0",
                "Origin": "https://chatgpt.com",
                "Referer": "https://chatgpt.com/",
            }
        )
        if str(proxy_url or "").strip():
            session.proxies.update({"http": proxy_url, "https": proxy_url})
        return session


def _warmup_chatgpt_subscription_session(session: Any) -> None:
    """Best-effort warmup after temporary subscription 401/403 responses."""
    for url, headers in (
        ("https://chatgpt.com/api/auth/session", {}),
        (
            f"{CHATGPT_ACCOUNT_CHECK_URL}?timezone_offset_min={_browser_timezone_offset_min()}",
            {
                "x-openai-target-path": CHATGPT_ACCOUNT_CHECK_PATH,
                "x-openai-target-route": CHATGPT_ACCOUNT_CHECK_PATH,
            },
        ),
    ):
        try:
            session.get(url, headers=headers, timeout=10)
        except Exception:
            continue


def query_chatgpt_subscription(access_token: str, account_id: str = "", proxy_url: str = "") -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少 ChatGPT account_id，无法查询订阅")
    session = _new_chatgpt_subscription_session(access_token, proxy_url=proxy_url)
    target_path = CHATGPT_SUBSCRIPTIONS_PATH
    query = f"?account_id={quote(account_id)}"
    extra_headers = {
        "x-openai-target-path": target_path,
        "x-openai-target-route": target_path,
    }
    urls = [
        f"{CHATGPT_SUBSCRIPTIONS_URL}{query}",
        f"{CHATGPT_SUBSCRIPTIONS_FALLBACK_URL}{query}",
    ]
    auth_errors: list[int] = []
    last_error: Exception | None = None
    last_status = 0
    no_subscription_404 = False

    raw: dict[str, Any] | None = None
    queried_url = ""
    for attempt in range(CHATGPT_SUBSCRIPTION_MAX_ATTEMPTS):
        attempt_auth_error = False
        for url in urls:
            try:
                resp = session.get(url, headers=extra_headers, timeout=30)
                last_status = int(getattr(resp, "status_code", 0) or 0)
                if last_status in {401, 403}:
                    attempt_auth_error = True
                    auth_errors.append(last_status)
                    continue
                if last_status == 404:
                    no_subscription_404 = True
                    last_error = RuntimeError("HTTP 404")
                    continue
                resp.raise_for_status()
                raw = resp.json()
            except Exception as exc:
                last_error = exc
                continue
            if not isinstance(raw, dict):
                raise HTTPException(status_code=502, detail="ChatGPT 订阅接口返回格式异常")
            queried_url = url
            break
        if raw is not None:
            break
        if no_subscription_404:
            break
        if attempt_auth_error and attempt < CHATGPT_SUBSCRIPTION_MAX_ATTEMPTS - 1:
            _warmup_chatgpt_subscription_session(session)

    if raw is None:
        if no_subscription_404:
            raw = {}
            queried_url = urls[0]
        elif auth_errors:
            raise HTTPException(
                status_code=403, detail="ChatGPT 订阅接口临时拒绝，请稍后重试；如果持续失败再刷新该账号 auth_session"
            )
        else:
            detail = f"ChatGPT 订阅接口请求失败: {last_error or f'HTTP {last_status}'}"
            raise HTTPException(status_code=502, detail=detail)

    account_check_url = CHATGPT_ACCOUNT_CHECK_URL
    if queried_url.startswith("https://chat.openai.com/"):
        account_check_url = CHATGPT_ACCOUNT_CHECK_FALLBACK_URL
    account_check_query = f"?timezone_offset_min={_browser_timezone_offset_min()}"
    account_check_headers = {
        "x-openai-target-path": CHATGPT_ACCOUNT_CHECK_PATH,
        "x-openai-target-route": CHATGPT_ACCOUNT_CHECK_PATH,
    }
    account_check_raw: dict[str, Any] = {}
    try:
        resp = session.get(f"{account_check_url}{account_check_query}", headers=account_check_headers, timeout=30)
        if int(getattr(resp, "status_code", 0) or 0) < 400:
            candidate = resp.json()
            if isinstance(candidate, dict) and isinstance(candidate.get("accounts"), dict):
                account_check_raw = candidate
    except Exception:
        account_check_raw = {}

    merged_raw = {"subscription": raw, "account_check": account_check_raw} if account_check_raw else raw
    return {"raw": merged_raw, "queried_url": queried_url}


def _normalize_mail_provider_name(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "cloudflare": "cloudflare-temp-email",
        "cloudflare-temp": "cloudflare-temp-email",
        "cloudflare-temp-email": "cloudflare-temp-email",
        "cloud-mail": "cloud-mail",
        "cloudmail": "cloud-mail",
        "mail.com": "mail.com",
        "mailcom": "mail.com",
        "mail-com": "mail.com",
        "outlook": "outlook",
        "hotmail": "outlook",
        "microsoft": "outlook",
        "microsoft-outlook": "outlook",
        "luckmail": "luckmail",
        "lucky-mail": "luckmail",
        "generic-api": "generic-api",
        "genericapi": "generic-api",
        "通用api": "generic-api",
        "通用-api": "generic-api",
        "mailu": "mailu",
        "self-mailu": "mailu",
    }
    return aliases.get(raw, raw)


def _normalize_mail_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _mail_recipient_candidates(account: dict[str, Any] | None, fallback_email: str) -> list[str]:
    candidates = [
        (account or {}).get("original_email"),
        (account or {}).get("display_email"),
        (account or {}).get("email"),
        fallback_email,
    ]
    out: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        email = _normalize_mail_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out


def _normalize_latest_mail(message: dict[str, Any]) -> dict[str, Any]:
    html = str(_first_present(message, "html", "body_html", default="") or "")
    text = str(_first_present(message, "text", "plain_text", "message", "body", "summary", default="") or "")
    content = str(_first_present(message, "content", default="") or "")
    if not html and content.lstrip().lower().startswith(("<!doctype", "<html", "<body", "<div", "<table")):
        html = content
    return {
        "id": str(_first_present(message, "id", "message_id", "messageId", default="")).strip(),
        "subject": str(_first_present(message, "subject", "title", default="")).strip(),
        "sendEmail": str(_first_present(message, "sendEmail", "from", "sender", "fromEmail", default="")).strip(),
        "toEmail": str(_first_present(message, "toEmail", "accountEmail", "email", "recipient", default="")).strip(),
        "text": text,
        "html": html,
        "content": html or content or text,
        "createTime": _first_present(
            message, "createTime", "createdAt", "received_at", "receivedAt", "date", "time", default=""
        ),
        "createdAt": _first_present(
            message, "createdAt", "createTime", "received_at", "receivedAt", "date", "time", default=""
        ),
        "raw": message.get("raw", {}),
    }


def _provider_order(provider: str, account: dict[str, Any] | None, recipients: list[str]) -> list[str]:
    provider = _normalize_mail_provider_name(provider)
    order: list[str] = []

    def add(name: str) -> None:
        normalized = _normalize_mail_provider_name(name)
        if normalized and normalized not in order:
            order.append(normalized)

    if provider:
        add(provider)
    if str((account or {}).get("mailapi_url") or "").strip():
        add("generic-api")

    cloudmail_account_id = str((account or {}).get("cloudmail_account_id") or "").strip()
    if cloudmail_account_id:
        add("cloudflare-temp-email")
        add("cloud-mail")

    for email in recipients:
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain == "mail.com":
            add("mail.com")
        if domain in {"outlook.com", "hotmail.com", "live.com", "msn.com"} or domain.startswith("outlook."):
            add("outlook")
            add("luckmail")

    add("mail.com")
    add("outlook")
    add("luckmail")
    if cloudmail_account_id:
        add("cloudflare-temp-email")
        add("cloud-mail")
    return order


def _fetch_latest_mail_with_provider(
    provider: str, recipient: str, account: dict[str, Any] | None
) -> list[dict[str, Any]]:
    provider = _normalize_mail_provider_name(provider)
    account_id = str((account or {}).get("cloudmail_account_id") or "").strip() or None
    if provider == "mail.com":
        from autotoken.mail.mailcom import MailComMailProvider

        return MailComMailProvider().search_emails_by_recipient(recipient, size=1, account_id=recipient)
    if provider == "outlook":
        from autotoken.mail.outlook import OutlookMailProvider

        return OutlookMailProvider().search_emails_by_recipient(recipient, size=1, account_id=recipient)
    if provider == "luckmail":
        from autotoken.mail.luckmail import LuckMailProvider

        return LuckMailProvider().search_emails_by_recipient(recipient, size=1, account_id=recipient)
    if provider == "icloud":
        from autotoken.mail.icloud import ICloudMailProvider

        return ICloudMailProvider().search_emails_by_recipient(recipient, size=1, account_id=recipient)
    if provider == "generic-api":
        from autotoken.mail.generic_api import GenericApiAccount, GenericApiMailProvider
        from autotoken.storage.generic_api_pool import get_cached_mail_message

        mailapi_url = str((account or {}).get("mailapi_url") or "").strip()
        client = GenericApiMailProvider()
        if mailapi_url:
            direct_account = GenericApiAccount(email=recipient, receive_code_url=mailapi_url)
            messages = client._fetch_receive_code_messages(direct_account, count=1)
            if messages:
                return messages
        messages = client.search_emails_by_recipient(recipient, size=1, account_id=recipient)
        if messages:
            return messages
        cached = get_cached_mail_message(recipient)
        return [cached] if cached else []
    if provider == "mailu":
        from autotoken.mail.mailu import MailuMailProvider

        return MailuMailProvider().search_emails_by_recipient(recipient, size=1, account_id=recipient)
    if provider == "cloud-mail":
        from autotoken.mail.cloud_mail import CloudMailProviderClient

        return CloudMailProviderClient().search_emails_by_recipient(recipient, size=1, account_id=account_id)
    if provider == "cloudflare-temp-email":
        from autotoken.mail.cloudflare_temp_email import CloudflareTempEmailClient

        return CloudflareTempEmailClient().search_emails_by_recipient(recipient, size=1, account_id=account_id)
    return []


def create_account_overview_router(
    *,
    load_accounts_with_session_stubs: Callable[..., list[dict]],
    sanitize_accounts_batch: Callable[[list[dict], dict | None], list[dict]],
    sanitize_account: Callable[[dict], dict],
    is_main_account_email: Callable[[str], bool],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/accounts")
    def get_accounts(
        include_session_stubs: bool = True,
    ):
        """获取所有账号列表；仪表盘分页、筛选和排序在前端完成。"""
        accounts = load_accounts_with_session_stubs(include_session_stubs=include_session_stubs)
        quota_cache = {
            account["email"]: account.get("last_quota")
            for account in accounts
            if isinstance(account.get("last_quota"), dict) and account.get("email")
        }
        return sanitize_accounts_batch(accounts, quota_cache)

    @router.get("/api/accounts/{email}/codex-auth")
    def get_codex_auth(email: str):
        """导出账号的 Codex CLI 格式认证文件（~/.codex/auth.json）"""
        email, auth_file, auth_data = _load_account_auth_data(email)

        access_token = _extract_access_token(auth_data)
        account_id = _extract_account_id(auth_data)

        codex_auth = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": auth_data.get("id_token", ""),
                "access_token": access_token,
                "refresh_token": auth_data.get("refresh_token", ""),
                "account_id": account_id,
            },
            "last_refresh": auth_data.get("last_refresh", ""),
        }

        return {
            "email": email,
            "codex_auth": codex_auth,
            "auth_file": auth_file,
            "hint": "将内容保存到 ~/.codex/auth.json（Linux/macOS）或 %APPDATA%\\codex\\auth.json（Windows）",
        }

    def _load_account_auth_data(email: str, *, prefer_auth_session: bool = False) -> tuple[str, str, dict[str, Any]]:
        from autotoken.auth.codex_auth import get_saved_main_auth_file
        from autotoken.storage.accounts import find_account, load_accounts
        from autotoken.storage.auth_files import (
            read_auth_json_file,
            trusted_auth_file_path,
            trusted_auth_or_session_path,
        )
        from autotoken.storage.auth_session_store import get_auth_session_file
        from autotoken.storage.auth_storage import AUTH_DIR

        normalized = email.strip().lower()

        if is_main_account_email(normalized):
            auth_file = get_saved_main_auth_file()
            if not auth_file or not Path(auth_file).exists():
                raise HTTPException(status_code=404, detail="主号没有可导出的认证文件")
            try:
                auth_data = read_auth_json_file(auth_file)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"认证文件无法读取: {exc}") from exc
            if not isinstance(auth_data, dict):
                raise HTTPException(status_code=400, detail="认证文件格式异常")
            return normalized, auth_file, auth_data

        candidates: list[Path] = []
        seen_paths: set[str] = set()
        first_error = None
        first_data: tuple[str, dict[str, Any]] | None = None

        def add_candidate(path: Path | None):
            if not path:
                return
            resolved = str(path.resolve())
            if resolved in seen_paths:
                return
            seen_paths.add(resolved)
            candidates.append(path)

        if prefer_auth_session:
            candidate = str(get_auth_session_file(normalized) or "").strip()
            session_path = trusted_auth_or_session_path(candidate, auth_dir=AUTH_DIR)
            if session_path:
                try:
                    auth_data = read_auth_json_file(session_path)
                except Exception as exc:
                    first_error = exc
                else:
                    if isinstance(auth_data, dict):
                        first_data = (str(session_path), auth_data)
                        if _extract_access_token(auth_data):
                            return normalized, str(session_path), auth_data
                    else:
                        first_error = ValueError("认证文件格式异常")
                add_candidate(session_path)

        account = find_account(load_accounts(), normalized)

        if account:
            candidate = str(account.get("auth_file") or "").strip()
            if candidate:
                add_candidate(trusted_auth_file_path(candidate, auth_dir=AUTH_DIR))

        if not prefer_auth_session:
            candidate = str(get_auth_session_file(normalized) or "").strip()
            add_candidate(trusted_auth_or_session_path(candidate, auth_dir=AUTH_DIR))

        if not candidates:
            raise HTTPException(status_code=404, detail="该账号没有认证文件")

        for auth_path in candidates:
            try:
                auth_data = read_auth_json_file(auth_path)
            except Exception as exc:
                if not prefer_auth_session:
                    raise HTTPException(status_code=400, detail=f"认证文件无法读取: {exc}") from exc
                if first_error is None:
                    first_error = exc
                continue
            if not isinstance(auth_data, dict):
                if not prefer_auth_session:
                    raise HTTPException(status_code=400, detail="认证文件格式异常")
                if first_error is None:
                    first_error = ValueError("认证文件格式异常")
                continue
            if first_data is None:
                first_data = (str(auth_path), auth_data)
            if not prefer_auth_session or _extract_access_token(auth_data):
                return normalized, str(auth_path), auth_data

        if first_data is not None:
            return normalized, first_data[0], first_data[1]
        raise HTTPException(status_code=400, detail=f"认证文件无法读取: {first_error}") from first_error

    @router.get("/api/accounts/{email}/access-token")
    def get_account_access_token(email: str):
        """获取账号 ChatGPT access_token，供仪表盘直接复制。"""
        email, _auth_file, auth_data = _load_account_auth_data(email, prefer_auth_session=True)
        access_token = _extract_access_token(auth_data)
        if not access_token:
            raise HTTPException(status_code=404, detail="该账号认证文件缺少 access_token")
        return {"email": email, "access_token": access_token}

    @router.post("/api/accounts/export-access-tokens")
    def export_account_access_tokens(params: ExportAccessTokensParams):
        """批量导出所选账号的 ChatGPT access_token。"""
        emails: list[str] = []
        seen: set[str] = set()
        for item in params.emails or []:
            email = str(item or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                emails.append(email)
        if not emails:
            raise HTTPException(status_code=400, detail="emails 不能为空")

        items: list[dict[str, str]] = []
        missing: list[dict[str, str]] = []
        for email in emails:
            try:
                normalized, _auth_file, auth_data = _load_account_auth_data(email, prefer_auth_session=True)
                access_token = _extract_access_token(auth_data)
                if not access_token:
                    raise HTTPException(status_code=404, detail="该账号认证文件缺少 access_token")
                items.append({"email": normalized, "access_token": access_token})
            except HTTPException as exc:
                missing.append({"email": email, "error": str(exc.detail or f"HTTP {exc.status_code}")})

        content = "\n".join(item["access_token"] for item in items)
        return {
            "count": len(items),
            "total": len(emails),
            "missing": missing,
            "items": items,
            "content": content,
            "filename": f"access-tokens-{datetime.now(UTC).strftime('%Y-%m-%d')}.txt",
        }

    @router.get("/api/accounts/{email}/subscription")
    def get_account_subscription(email: str):
        """查询 ChatGPT 账号实时订阅状态。"""
        email, _auth_file, auth_data = _load_account_auth_data(email, prefer_auth_session=True)
        access_token = _extract_access_token(auth_data)
        if not access_token:
            raise HTTPException(status_code=404, detail="该账号认证文件缺少 access_token")
        account_id = _extract_account_id(auth_data)
        result = query_chatgpt_subscription(access_token, account_id=account_id)
        raw = result.get("raw") if isinstance(result, dict) else {}
        if not isinstance(raw, dict):
            raise HTTPException(status_code=502, detail="ChatGPT 订阅接口返回格式异常")
        normalized = normalize_chatgpt_subscription(raw, account_id=account_id)
        available_plans = normalized.get("available_plans") if isinstance(normalized, dict) else []
        if isinstance(available_plans, list) and available_plans:
            try:
                from autotoken.storage.accounts import update_account

                update_account(
                    email,
                    trial_eligible=True,
                    trial_available_plans=[str(item) for item in available_plans if str(item or "").strip()],
                    trial_checked_at=time.time(),
                )
            except Exception:
                pass
        return {
            "email": email,
            "account_id": account_id,
            "subscription": {
                **normalized,
                "jwt_plan_type": _extract_jwt_plan_type(access_token),
            },
            "raw": raw,
            "queried_url": result.get("queried_url") if isinstance(result, dict) else CHATGPT_SUBSCRIPTIONS_URL,
        }

    @router.get("/api/accounts/{email}/latest-mail")
    def get_account_latest_mail(email: str):
        """获取账号对应邮箱的最近一封邮件。"""
        from autotoken.storage.accounts import find_account, load_accounts

        normalized = email.strip().lower()
        account = find_account(load_accounts(), normalized)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

        recipients = _mail_recipient_candidates(account, normalized)
        providers = _provider_order(str(account.get("mail_provider") or ""), account, recipients)
        errors: list[str] = []
        attempted = 0
        for provider in providers:
            for recipient in recipients:
                attempted += 1
                try:
                    messages = _fetch_latest_mail_with_provider(provider, recipient, account)
                except Exception as exc:
                    errors.append(
                        f"{provider}/{recipient}: {safe_error}"
                        if (safe_error := str(exc).strip())
                        else f"{provider}/{recipient}: 失败"
                    )
                    continue
                if messages:
                    return {
                        "email": normalized,
                        "mail_email": recipient,
                        "provider": provider,
                        "message": _normalize_latest_mail(messages[0]),
                    }
        if attempted:
            return {
                "email": normalized,
                "mail_email": recipients[0] if recipients else normalized,
                "provider": providers[0] if providers else "",
                "message": None,
                "errors": errors[:5],
            }
        raise HTTPException(status_code=404, detail="该账号没有可用邮箱取件配置")

    @router.get("/api/accounts/active")
    def get_active():
        """获取活跃账号"""
        from autotoken.storage.accounts import get_active_accounts

        return [sanitize_account(account) for account in get_active_accounts()]

    @router.get("/api/accounts/standby")
    def get_standby():
        """获取待命账号"""
        from autotoken.storage.accounts import get_standby_accounts

        return [sanitize_account(account) for account in get_standby_accounts()]

    return router
