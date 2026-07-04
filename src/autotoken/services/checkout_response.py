"""Pure checkout response parsing and normalization helpers."""

import json
import re
from typing import Any


def looks_like_html_error(text: str) -> bool:
    compact = str(text or "").strip().lower()
    if not compact:
        return False
    return compact.startswith(("<!doctype html", "<html")) or "<head" in compact[:200]


def friendly_checkout_error(detail: str, status: int | None = None) -> str:
    text = str(detail or "").strip()
    if not text:
        return f"上游错误({status or 502})"
    if looks_like_html_error(text):
        if status == 403:
            return "生成 checkout 被上游 403 拦截，返回了 HTML 风控页；通常是账号 access_token 失效、Cloudflare 未通过，或当前 IP/环境被风控"
        return f"生成 checkout 返回了 HTML 页面（HTTP {status or 502}），通常是会话未通过或遭遇风控"
    lowered = text.lower()
    if status == 403 and ("forbidden" in lowered or "denied" in lowered):
        return "生成 checkout 被上游 403 拦截；通常是账号 access_token 失效、Cloudflare 未通过，或当前 IP/环境被风控"
    return text


def looks_like_cloudflare_challenge(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "_cf_chl_opt" in lowered
        or "enable javascript and cookies to continue" in lowered
        or "cf-chl" in lowered
        or "verify you are human" in lowered
    )


def parse_checkout_response_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except json.JSONDecodeError:
        return {"detail": text or "upstream returned non-json response"}


def find_hosted_checkout_url(payload: Any) -> str:
    pay_openai_pattern = re.compile(r"^https://(?:pay\.openai\.com|checkout\.stripe\.com)/c/pay/", re.I)
    stack = [payload]
    while stack:
        current = stack.pop(0)
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        for value in current.values():
            if isinstance(value, str) and pay_openai_pattern.match(value.strip()):
                return value.strip()
            if isinstance(value, (dict, list)):
                stack.append(value)
    return ""


def choose_checkout_error_status(upstream_status: int) -> int:
    if upstream_status in (400, 401, 403, 404, 409, 422, 429):
        return upstream_status
    return 502


def normalize_checkout_payload_for_http(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    plan_name = str(normalized.get("plan_name") or "").strip().lower()
    if not plan_name:
        normalized["plan_name"] = "chatgptplusplan"
        plan_name = "chatgptplusplan"
    if plan_name == "chatgptplusplan":
        normalized.setdefault("entry_point", "all_plans_pricing_modal")
    billing_details = normalized.get("billing_details") if isinstance(normalized.get("billing_details"), dict) else {}
    normalized["billing_details"] = {
        "country": str(billing_details.get("country") or "US").strip().upper() or "US",
        "currency": str(billing_details.get("currency") or "USD").strip().upper() or "USD",
    }
    checkout_ui_mode = str(normalized.get("checkout_ui_mode") or "").strip().lower()
    if checkout_ui_mode:
        normalized["checkout_ui_mode"] = "hosted" if checkout_ui_mode == "hosted" else "custom"
    return normalized
