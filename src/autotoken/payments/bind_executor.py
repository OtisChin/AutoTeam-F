"""绑卡执行器。"""

from __future__ import annotations

import logging
import re
import time
import uuid

from autotoken.core.paths import PROJECT_ROOT
from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = PROJECT_ROOT / "data" / "bind_screenshots"

CARD_NUMBER_SELECTORS = [
    'input[autocomplete="cc-number"]',
    'input[name*="cardnumber" i]',
    'input[id*="cardnumber" i]',
    'input[placeholder*="card number" i]',
    'input[placeholder*="卡号"]',
]
EXPIRY_SELECTORS = [
    'input[autocomplete="cc-exp"]',
    'input[name*="exp" i]',
    'input[id*="exp" i]',
    'input[placeholder*="MM / YY" i]',
    'input[placeholder*="expiry" i]',
    'input[placeholder*="有效期"]',
]
CVC_SELECTORS = [
    'input[autocomplete="cc-csc"]',
    'input[name*="cvc" i]',
    'input[name*="cvv" i]',
    'input[id*="cvc" i]',
    'input[id*="cvv" i]',
    'input[placeholder*="CVC" i]',
    'input[placeholder*="CVV" i]',
]
NAME_SELECTORS = [
    'input[autocomplete="cc-name"]',
    'input[name*="name" i]',
    'input[id*="name" i]',
    'input[placeholder*="name on card" i]',
    'input[placeholder*="姓名"]',
]
ADDRESS_SELECTORS = [
    'input[autocomplete="billing address-line1"]',
    'input[name*="address" i]',
    'input[id*="address" i]',
    'textarea[name*="address" i]',
    'textarea[id*="address" i]',
    'input[placeholder*="address" i]',
    'input[placeholder*="地址"]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button[data-testid*="submit" i]',
    'button[data-testid*="pay" i]',
    'button:has-text("Pay")',
    'button:has-text("支付")',
    'button:has-text("Subscribe")',
]

SUCCESS_HINTS = (
    "payment successful",
    "thanks for subscribing",
    "subscription active",
    "you are now subscribed",
    "付款成功",
    "支付成功",
    "订阅成功",
)
FAILURE_HINTS = (
    "card was declined",
    "payment failed",
    "your card was declined",
    "incorrect cvc",
    "expired card",
    "insufficient funds",
    "declined",
    "支付失败",
    "付款失败",
    "银行卡被拒绝",
)
REVIEW_HINTS = (
    "authentication required",
    "verify your purchase",
    "complete the verification",
    "需要验证",
    "请完成验证",
    "3d secure",
)


def normalize_expiry(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""

    for pattern in (
        r"^(?P<year>\d{4})/(?P<month>\d{1,2})$",
        r"^(?P<month>\d{1,2})/(?P<year>\d{2,4})$",
        r"^(?P<year>\d{4})-(?P<month>\d{1,2})$",
    ):
        matched = re.match(pattern, text)
        if not matched:
            continue
        month = matched.group("month").zfill(2)
        year = matched.group("year")[-2:]
        return f"{month}/{year}"

    digits = re.sub(r"\D+", "", text)
    if len(digits) == 6:
        return f"{digits[4:6]}/{digits[2:4]}"
    if len(digits) == 4:
        return f"{digits[:2]}/{digits[2:]}"
    return text


def extract_card_payload(card_item: dict) -> dict:
    meta = card_item.get("meta") if isinstance(card_item, dict) else {}
    content = meta.get("content") if isinstance(meta, dict) and isinstance(meta.get("content"), dict) else meta
    content = content if isinstance(content, dict) else {}
    return {
        "card_number": str(content.get("card_number") or card_item.get("value") or "").strip(),
        "expiry_date": normalize_expiry(content.get("expiry_date") or card_item.get("expires_at") or ""),
        "cvv": str(content.get("cvv") or "").strip(),
        "name": str(content.get("name") or "").strip(),
        "address": str(content.get("address") or "").strip(),
        "phone": str(content.get("phone") or "").strip(),
        "sms_api": str(content.get("sms_api") or "").strip(),
    }


def classify_checkout_state(url: str, body_text: str):
    normalized_url = str(url or "").strip().lower()
    normalized_body = str(body_text or "").strip().lower()
    haystack = f"{normalized_url}\n{normalized_body}"

    if any(hint in haystack for hint in SUCCESS_HINTS):
        return {
            "status": "success",
            "failure_stage": "",
            "message": "检测到支付成功页面",
        }

    if any(hint in haystack for hint in FAILURE_HINTS):
        return {
            "status": "failed",
            "failure_stage": "post_submit",
            "message": "检测到支付失败提示",
        }

    if any(hint in haystack for hint in REVIEW_HINTS):
        return {
            "status": "needs_review",
            "failure_stage": "post_submit",
            "message": "检测到需要额外验证或人工确认",
        }

    return None


def _build_result(status: str, *, failure_stage: str = "", message: str = "", screenshot_paths: list[str] | None = None):
    return {
        "status": status,
        "failure_stage": failure_stage,
        "message": message,
        "screenshot_paths": screenshot_paths or [],
    }


def _capture_screenshot(api: ChatGPTTeamAPI, session_id: str, stage: str, screenshot_paths: list[str]):
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{session_id}-{stage}.png"
        api.page.screenshot(path=str(path), full_page=True, timeout=5000)
        screenshot_paths.append(str(path))
        return str(path)
    except Exception as exc:
        logger.warning("[bind_executor] 截图失败(%s): %s", stage, exc)
        return ""


def _locator_from_selectors(api: ChatGPTTeamAPI, selectors: list[str], timeout_ms: int = 4000):
    return api._visible_locator_in_frames(selectors, timeout_ms=timeout_ms)


def _fill_field(api: ChatGPTTeamAPI, selectors: list[str], value: str, label: str, *, required: bool = True):
    if not value:
        if required:
            return _build_result("failed", failure_stage="fill_card", message=f"缺少 {label}")
        return None

    locator = _locator_from_selectors(api, selectors)
    if not locator:
        if required:
            return _build_result("failed", failure_stage="fill_card", message=f"未找到 {label} 输入框")
        return None

    try:
        locator.click(timeout=1500)
    except Exception:
        pass
    try:
        locator.fill(value, timeout=3000)
    except Exception as exc:
        return _build_result("failed", failure_stage="fill_card", message=f"填写 {label} 失败: {exc}")
    return None


def _submit_checkout(api: ChatGPTTeamAPI):
    locator = _locator_from_selectors(api, SUBMIT_SELECTORS)
    if not locator:
        return _build_result("failed", failure_stage="submit", message="未找到提交支付按钮")
    try:
        locator.click(timeout=3000)
    except Exception as exc:
        return _build_result("failed", failure_stage="submit", message=f"点击提交按钮失败: {exc}")
    return None


def _body_excerpt(api: ChatGPTTeamAPI, limit: int = 2000):
    try:
        return api.page.locator("body").inner_text(timeout=1500)[:limit]
    except Exception:
        return ""


def _wait_for_checkout_result(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
):
    deadline = time.time() + max(10, timeout_seconds)
    last_log_at = 0.0
    while time.time() < deadline:
        now = time.time()
        if now - last_log_at >= 60:
            remaining = max(0, int(deadline - now))
            logger.info(
                "[bind_executor] 等待支付结果中，剩余约 %ss，当前 URL=%s",
                remaining,
                getattr(api.page, "url", ""),
            )
            last_log_at = now

        if callable(is_cancelled) and is_cancelled():
            _capture_screenshot(api, session_id, "cancelled", screenshot_paths)
            return _build_result("failed", failure_stage="submit", message="任务已取消", screenshot_paths=screenshot_paths)

        body_text = _body_excerpt(api)
        classified = classify_checkout_state(getattr(api.page, "url", ""), body_text)
        if classified:
            _capture_screenshot(api, session_id, classified["status"], screenshot_paths)
            classified["screenshot_paths"] = screenshot_paths
            return classified

        time.sleep(3)

    _capture_screenshot(api, session_id, "timeout", screenshot_paths)
    return _build_result(
        "needs_review",
        failure_stage="post_submit",
        message="等待支付结果超时，需要人工确认最终状态",
        screenshot_paths=screenshot_paths,
    )


def run_bind_task(
    *,
    checkout_url: str,
    card_item: dict,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    manual_confirm: bool = True,
    timeout_seconds: int = 900,
    is_cancelled=None,
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []

    try:
        payload = extract_card_payload(card_item)
        api._launch_browser(
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            background=False if manual_confirm else None,
        )

        if callable(is_cancelled) and is_cancelled():
            return _build_result("failed", failure_stage="open_checkout", message="任务已取消")

        try:
            api.page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            _capture_screenshot(api, session_id, "open-checkout-failed", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="open_checkout",
                message=f"打开 checkout 页面失败: {exc}",
                screenshot_paths=screenshot_paths,
            )

        api._wait_for_cloudflare()
        _capture_screenshot(api, session_id, "opened", screenshot_paths)

        for selectors, value, label, required in (
            (CARD_NUMBER_SELECTORS, payload["card_number"], "卡号", True),
            (EXPIRY_SELECTORS, payload["expiry_date"], "有效期", True),
            (CVC_SELECTORS, payload["cvv"], "CVV", True),
            (NAME_SELECTORS, payload["name"], "姓名", False),
            (ADDRESS_SELECTORS, payload["address"], "账单地址", False),
        ):
            result = _fill_field(api, selectors, value, label, required=required)
            if result:
                result["screenshot_paths"] = screenshot_paths
                _capture_screenshot(api, session_id, "fill-card-failed", screenshot_paths)
                return result

        _capture_screenshot(api, session_id, "filled", screenshot_paths)

        if manual_confirm:
            logger.info(
                "[bind_executor] manual_confirm=true，已完成填卡，不会自动点击提交；等待人工在浏览器中继续操作，最长 %ss",
                timeout_seconds,
            )
            return _wait_for_checkout_result(
                api,
                session_id=session_id,
                screenshot_paths=screenshot_paths,
                timeout_seconds=timeout_seconds,
                is_cancelled=is_cancelled,
            )

        result = _submit_checkout(api)
        if result:
            result["screenshot_paths"] = screenshot_paths
            _capture_screenshot(api, session_id, "submit-failed", screenshot_paths)
            return result

        _capture_screenshot(api, session_id, "submitted", screenshot_paths)
        return _wait_for_checkout_result(
            api,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=timeout_seconds,
            is_cancelled=is_cancelled,
        )
    except Exception as exc:
        logger.exception("[bind_executor] unexpected error")
        _capture_screenshot(api, session_id, "unexpected-error", screenshot_paths)
        return _build_result(
            "failed",
            failure_stage="post_submit",
            message=f"执行绑卡任务时出现异常: {exc}",
            screenshot_paths=screenshot_paths,
        )
    finally:
        try:
            api.stop()
        except Exception:
            pass
