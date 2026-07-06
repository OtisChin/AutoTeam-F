"""绑卡执行器。"""

from __future__ import annotations

import logging
import re
import time
import uuid

from autotoken.core.paths import PROJECT_ROOT
from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI
from autotoken.services import chatgpt_session as chatgpt_session_service
from autotoken.services import payment_form_fields as payment_form_fields_service
from autotoken.storage.auth_session_store import load_auth_session

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = PROJECT_ROOT / "data" / "bind_screenshots"

CARD_NUMBER_SELECTORS = [
    '#payment-numberInput',
    'input[autocomplete="cc-number"]',
    'input[name="number"]',
    'input[id*="number" i]',
    'input[name*="cardnumber" i]',
    'input[id*="cardnumber" i]',
]
EXPIRY_SELECTORS = [
    '#payment-expiryInput',
    'input[autocomplete="cc-exp"]',
    'input[name="expiry"]',
    'input[name="exp-date"]',
    'input[id*="expiry" i]',
    'input[name*="exp" i]',
    'input[id*="exp" i]',
]
CVC_SELECTORS = [
    '#payment-cvcInput',
    'input[autocomplete="cc-csc"]',
    'input[name*="cvc" i]',
    'input[name*="cvv" i]',
    'input[name="cvc"]',
    'input[id*="securityCode" i]',
    'input[id*="cvc" i]',
    'input[id*="cvv" i]',
]
NAME_SELECTORS = [
    'input[autocomplete="cc-name"]',
    'input[autocomplete="name"]',
    'input[name="name"]',
    'input[name*="name" i]',
    'input[id*="name" i]',
]
BILLING_NAME_SELECTORS = [
    '#billingAddress-nameInput',
    'input[name="name"]',
    'input[autocomplete="billing name"]',
    'input[autocomplete="name"]',
    '[data-field="name"] input',
    'input[name="billingAddress.name" i]',
    'input[id="billingAddress-name" i]',
    'input[name$="[billingAddress][name]" i]',
    'input[name$="[billing_address][name]" i]',
    'input[name$=".billingAddress.name" i]',
    'input[name$="billingAddress.name" i]',
    'input[name$="billing_address.name" i]',
    'input[name$="billingName" i]',
    'input[id*="billing" i][id*="name" i]',
    'input[name*="billing" i][name*="name" i]',
]
COUNTRY_SELECTORS = [
    '#billingAddress-countryInput',
    'select[name="country"]',
    'select[autocomplete="billing country"]',
    'select[autocomplete*="country" i]',
    'select[name*="country" i]',
    'select[id*="country" i]',
    'input[autocomplete*="country" i]',
    'input[name*="country" i]',
    'input[id*="country" i]',
]
ADDRESS_SELECTORS = [
    '#billingAddress-addressLine1Input',
    'input[name="addressLine1"]',
    'input[autocomplete="billing address-line1"]',
    'input[autocomplete="address-line1"]',
    'input[name="address-line1" i]',
    'input[id="address-line1" i]',
    'input[name$="[address][line1]" i]',
    'input[name$=".address.line1" i]',
    'input[name$="address.line1" i]',
    'input[name$="addressLine1" i]',
    'input[name*="line1" i]',
    'input[id*="line1" i]',
    'textarea[autocomplete="billing address-line1"]',
    'textarea[autocomplete="address-line1"]',
    'textarea[name*="line1" i]',
    'textarea[id*="line1" i]',
]
CITY_SELECTORS = [
    '#billingAddress-localityInput',
    'input[name="locality"]',
    'input[autocomplete="billing address-level2"]',
    'input[autocomplete="address-level2"]',
    'input[name*="city" i]',
    'input[id*="city" i]',
]
STATE_SELECTORS = [
    '#billingAddress-administrativeAreaInput',
    'select[name="administrativeArea"]',
    'input[name="administrativeArea"]',
    'input[autocomplete="billing address-level1"]',
    'input[autocomplete="address-level1"]',
    'select[autocomplete="billing address-level1"]',
    'select[autocomplete="address-level1"]',
    'input[name*="state" i]',
    'input[id*="state" i]',
    'select[name*="state" i]',
    'select[id*="state" i]',
]
POSTAL_CODE_SELECTORS = [
    '#billingAddress-postalCodeInput',
    'input[name="postalCode"]',
    'input[autocomplete="billing postal-code"]',
    'input[autocomplete="postal-code"]',
    'input[name*="postal" i]',
    'input[id*="postal" i]',
    'input[name*="zip" i]',
    'input[id*="zip" i]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button[data-testid*="submit" i]',
    'button[data-testid*="pay" i]',
    'input[type="submit"]',
]

CARD_NUMBER_WAIT_TIMEOUT_MS = 90_000
PAYMENT_FIELD_WAIT_TIMEOUT_MS = 15_000
TAX_FREE_US_STATES = {"AK", "DE", "MT", "NH", "OR"}
TAX_FREE_BILLING_FALLBACKS = (
    {
        "name": "John Doe",
        "country": "US",
        "state": "OR",
        "city": "Portland",
        "zip": "97201",
        "address1": "800 SW 5th Ave",
        "address2": "",
        "phone_number": "503-555-0182",
    },
    {
        "name": "John Doe",
        "country": "US",
        "state": "DE",
        "city": "Wilmington",
        "zip": "19801",
        "address1": "1201 N Market St",
        "address2": "",
        "phone_number": "302-555-0182",
    },
    {
        "name": "John Doe",
        "country": "US",
        "state": "NH",
        "city": "Concord",
        "zip": "03301",
        "address1": "2 Eagle Square",
        "address2": "",
        "phone_number": "603-555-0182",
    },
    {
        "name": "John Doe",
        "country": "US",
        "state": "MT",
        "city": "Billings",
        "zip": "59101",
        "address1": "401 N Broadway",
        "address2": "",
        "phone_number": "406-555-0182",
    },
    {
        "name": "John Doe",
        "country": "US",
        "state": "AK",
        "city": "Anchorage",
        "zip": "99501",
        "address1": "632 W 6th Ave",
        "address2": "",
        "phone_number": "907-555-0182",
    },
)

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


def _normalize_generated_billing_address(source: dict | None) -> dict[str, str]:
    source = source if isinstance(source, dict) else {}
    state = str(source.get("state") or source.get("State") or "").strip().upper()
    return {
        "name": str(source.get("name") or source.get("full_name") or source.get("Full_Name") or "").strip(),
        "country": str(source.get("country") or source.get("Country") or "US").strip().upper() or "US",
        "state": state,
        "city": str(source.get("city") or source.get("City") or "").strip(),
        "zip": str(
            source.get("zip")
            or source.get("postal_code")
            or source.get("postalCode")
            or source.get("Zip_Code")
            or ""
        ).strip(),
        "address1": str(
            source.get("address1")
            or source.get("address")
            or source.get("Address")
            or source.get("line1")
            or ""
        ).strip(),
        "address2": str(source.get("address2") or source.get("line2") or "").strip(),
        "phone_number": str(source.get("phone_number") or source.get("phone") or source.get("Telephone") or "").strip(),
    }


def _billing_address_complete(address: dict[str, str]) -> bool:
    return all(
        str(address.get(key) or "").strip()
        for key in ("country", "state", "city", "zip", "address1")
    )


def generate_tax_free_billing_address(*, fetch_billing_address=None, max_attempts: int = 8) -> dict[str, str]:
    if fetch_billing_address is None:
        from autotoken.payments.gopay_executor import _fetch_random_billing_address

        fetch_billing_address = _fetch_random_billing_address

    for _attempt in range(max(1, int(max_attempts or 1))):
        try:
            candidate = _normalize_generated_billing_address(fetch_billing_address())
        except Exception as exc:
            logger.info("[bind_executor] 免税州账单地址生成失败，使用 fallback: %s", exc)
            break
        if (
            candidate.get("country") == "US"
            and candidate.get("state") in TAX_FREE_US_STATES
            and _billing_address_complete(candidate)
        ):
            return candidate

    fallback_index = int(time.time()) % len(TAX_FREE_BILLING_FALLBACKS)
    return dict(TAX_FREE_BILLING_FALLBACKS[fallback_index])


def extract_card_payload(card_item: dict) -> dict:
    meta = card_item.get("meta") if isinstance(card_item, dict) else {}
    content = meta.get("content") if isinstance(meta, dict) and isinstance(meta.get("content"), dict) else meta
    content = content if isinstance(content, dict) else {}

    return {
        "card_number": str(content.get("card_number") or card_item.get("value") or "").strip(),
        "expiry_date": normalize_expiry(content.get("expiry_date") or card_item.get("expires_at") or ""),
        "cvv": str(content.get("cvv") or "").strip(),
        "name": str(content.get("name") or "").strip(),
        "address": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": "",
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


CHECKOUT_NETWORK_CAPTURE_MARKERS = (
    "/v1/confirmation_tokens",
    "/v1/payment_intents/",
    "/v1/payment_pages/",
    "/backend-api/payments/checkout/confirm",
)


def _new_checkout_network_capture() -> dict:
    return {
        "responses": [],
        "payment_intent": {},
        "failure_reason": {},
    }


def _checkout_network_url_relevant(url: str) -> bool:
    raw = str(url or "")
    return any(marker in raw for marker in CHECKOUT_NETWORK_CAPTURE_MARKERS)


def _payment_intent_id_from_url(url: str) -> str:
    matched = re.search(r"/payment_intents/(pi_[^/?#]+)", str(url or ""))
    return str(matched.group(1) if matched else "").strip()


def _compact_failure_parts(reason: dict) -> str:
    parts = [
        str(reason.get("code") or "").strip(),
        str(reason.get("decline_code") or "").strip(),
        str(reason.get("message") or "").strip(),
    ]
    return " / ".join(part for part in parts if part)


def _checkout_failure_reason_from_payload(payload: dict) -> dict[str, str]:
    data = payload if isinstance(payload, dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    if error:
        return {
            "code": str(error.get("code") or "").strip(),
            "decline_code": str(error.get("decline_code") or "").strip(),
            "message": str(error.get("message") or "").strip(),
            "type": str(error.get("type") or "").strip(),
        }

    payment_intent = data.get("payment_intent") if isinstance(data.get("payment_intent"), dict) else data
    if not isinstance(payment_intent, dict):
        return {}
    last_error = (
        payment_intent.get("last_payment_error")
        if isinstance(payment_intent.get("last_payment_error"), dict)
        else {}
    )
    if last_error:
        return {
            "code": str(last_error.get("code") or "").strip(),
            "decline_code": str(last_error.get("decline_code") or "").strip(),
            "message": str(last_error.get("message") or "").strip(),
            "type": str(last_error.get("type") or "").strip(),
        }
    latest_charge = payment_intent.get("latest_charge") if isinstance(payment_intent.get("latest_charge"), dict) else {}
    outcome = latest_charge.get("outcome") if isinstance(latest_charge.get("outcome"), dict) else {}
    if outcome:
        return {
            "code": "",
            "decline_code": str(outcome.get("reason") or "").strip(),
            "message": str(outcome.get("seller_message") or outcome.get("network_decline_code") or "").strip(),
            "type": str(outcome.get("type") or "").strip(),
        }
    return {}


def _capture_checkout_network_payload(capture: dict, *, url: str, status: int = 0, payload: dict | None = None) -> None:
    if not isinstance(capture, dict) or not _checkout_network_url_relevant(url):
        return
    data = payload if isinstance(payload, dict) else {}
    event = {
        "url": str(url or ""),
        "http_status": int(status or 0),
    }
    capture.setdefault("responses", []).append(event)
    payment_intent_payload = data.get("payment_intent") if isinstance(data.get("payment_intent"), dict) else data
    pi_id = (
        str(payment_intent_payload.get("id") or "").strip()
        if isinstance(payment_intent_payload, dict)
        else ""
    ) or _payment_intent_id_from_url(url)
    pi_status = (
        str(payment_intent_payload.get("status") or "").strip()
        if isinstance(payment_intent_payload, dict)
        else ""
    )
    reason = _checkout_failure_reason_from_payload(data)
    if pi_id or pi_status or reason:
        payment_intent = {
            "id": pi_id,
            "status": pi_status,
            "failure_reason": reason,
            "confirm_result": {
                "http_status": int(status or 0),
                "error": reason if reason else {},
            },
        }
        capture["payment_intent"] = payment_intent
    if reason:
        capture["failure_reason"] = reason


def _capture_checkout_network_response(capture: dict, response) -> None:
    url = str(getattr(response, "url", "") or "")
    if not _checkout_network_url_relevant(url):
        return
    try:
        status = int(getattr(response, "status", 0) or 0)
    except Exception:
        status = 0
    try:
        payload = response.json()
    except Exception:
        payload = {}
    _capture_checkout_network_payload(capture, url=url, status=status, payload=payload)


def _install_checkout_network_capture(api: ChatGPTTeamAPI, capture: dict) -> None:
    page = getattr(api, "page", None)
    if page is None or not hasattr(page, "on"):
        return

    def _on_response(response):
        try:
            _capture_checkout_network_response(capture, response)
        except Exception:
            logger.debug("[bind_executor] checkout network response capture failed", exc_info=True)

    try:
        page.on("response", _on_response)
    except Exception:
        logger.debug("[bind_executor] unable to install checkout network capture", exc_info=True)


def _enrich_checkout_result_with_network_failure(result: dict, capture: dict | None) -> dict:
    enriched = dict(result or {})
    capture = capture if isinstance(capture, dict) else {}
    payment_intent = capture.get("payment_intent") if isinstance(capture.get("payment_intent"), dict) else {}
    reason = capture.get("failure_reason") if isinstance(capture.get("failure_reason"), dict) else {}
    if not reason and isinstance(payment_intent.get("failure_reason"), dict):
        reason = payment_intent.get("failure_reason") or {}
    if not reason:
        return enriched

    if enriched.get("status") == "needs_review":
        enriched["status"] = "failed"
    enriched["failure_stage"] = enriched.get("failure_stage") or "post_submit"
    enriched["payment_intent"] = payment_intent or {"failure_reason": reason}
    detail = _compact_failure_parts(reason)
    if detail:
        current = str(enriched.get("message") or "").strip()
        if detail not in current:
            enriched["message"] = f"{current}，原因: {detail}" if current else f"银行卡支付未成功，原因: {detail}"
    return enriched


def _selected_account_auth_context(email: str) -> dict[str, str]:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return {}
    try:
        return chatgpt_session_service.extract_auth_session_context(
            normalized_email,
            load_session=load_auth_session,
        )
    except Exception as exc:
        logger.warning("[bind_executor] 读取 ChatGPT auth_session 失败(%s): %s", normalized_email, exc)
        return {}


def _inject_selected_account_auth_session(api: ChatGPTTeamAPI, auth_context: dict[str, str], email: str) -> bool:
    cookie_header = str(auth_context.get("cookie_header") or "").strip()
    session_token = str(auth_context.get("session_token") or "").strip()
    if not session_token and cookie_header:
        session_token = chatgpt_session_service.session_token_from_cookie_header(cookie_header)
    if not session_token:
        if str(email or "").strip():
            logger.warning("[bind_executor] 所选账号缺少可注入的 ChatGPT session token: %s", email)
        return False

    chatgpt_session_service.inject_chatgpt_browser_cookies(
        api,
        session_token=session_token,
        cookie_header=cookie_header,
        account_id=str(auth_context.get("account_id") or "").strip(),
        device_id=str(auth_context.get("device_id") or "").strip(),
    )
    logger.info("[bind_executor] 已注入 ChatGPT 登录 cookie；支付浏览器禁用 fingerprint/stealth 脚本")
    return True


def _open_checkout_from_fresh_payment_page(api: ChatGPTTeamAPI, checkout_url: str) -> None:
    """Keep the injected ChatGPT page alive and open checkout in a second page.

    Reloading/navigating the same page immediately after cookie injection can
    trip ChatGPT/Cloudflare checks.  Use one page as the login-state carrier and
    a fresh sibling page in the same browser context for the checkout itself.
    """

    if not getattr(api, "context", None) or not hasattr(api.context, "new_page"):
        api.page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
        return
    checkout_page = api.context.new_page()
    api.page = checkout_page
    checkout_page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)


def _warm_chatgpt_login_state_page(api: ChatGPTTeamAPI) -> None:
    page = getattr(api, "page", None)
    if page is None:
        return
    try:
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        api._wait_for_cloudflare()
        logger.info("[bind_executor] ChatGPT 登录态承载页已打开，checkout 将在同上下文新页打开")
    except Exception as exc:
        # Warm-up is best-effort.  The checkout page is still opened separately so
        # the original page does not get reloaded into the payment flow.
        logger.warning("[bind_executor] ChatGPT 登录态承载页预热失败，继续用新页打开 checkout: %s", exc)


def _auth_context_has_web_session(auth_context: dict[str, str]) -> bool:
    return bool(
        str(auth_context.get("session_token") or "").strip()
        or str(auth_context.get("cookie_header") or "").strip()
    )


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
    deadline = time.time() + max(0.1, timeout_ms / 1000)
    last_locator = None
    while time.time() < deadline:
        for selector in selectors:
            locator = api._visible_locator_in_frames([selector], timeout_ms=250)
            if locator:
                return locator
            last_locator = locator
        time.sleep(0.1)
    return last_locator


def _fill_field(
    api: ChatGPTTeamAPI,
    selectors: list[str],
    value: str,
    label: str,
    *,
    required: bool = True,
    timeout_ms: int = 4000,
):
    if not value:
        if required:
            return _build_result("failed", failure_stage="fill_card", message=f"缺少 {label}")
        return None

    locator = _locator_from_selectors(api, selectors, timeout_ms=timeout_ms)
    if not locator:
        if required:
            return _build_result("failed", failure_stage="fill_card", message=f"未找到 {label} 输入框")
        return None

    try:
        locator.click(timeout=1500)
    except Exception:
        pass
    try:
        if payment_form_fields_service.set_locator_value(
            locator,
            value,
            prefer_select_option=True,
            fill_fallback=True,
            dispatch_timeout=3000,
        ):
            return None
        raise RuntimeError("无法写入字段值")
    except Exception as exc:
        return _build_result("failed", failure_stage="fill_card", message=f"填写 {label} 失败: {exc}")
    return None


def _fill_billing_name_before_address(api: ChatGPTTeamAPI, name: str):
    name = str(name or "").strip()
    if not name:
        return None

    script = r"""({ name, addressSelectors }) => {
      const visible = (el) => {
        if (!el || el.disabled || el.readOnly) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return el.getClientRects().length > 0;
      };
      const y = (el) => el.getBoundingClientRect().top + window.scrollY;
      const x = (el) => el.getBoundingClientRect().left + window.scrollX;
      const setValue = (el, value) => {
        el.scrollIntoView({ behavior: 'instant', block: 'center' });
        el.focus?.();
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        if (descriptor?.set) descriptor.set.call(el, value);
        else el.value = value;
        let inputEvent;
        try {
          inputEvent = new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value });
        } catch (_) {
          inputEvent = new Event('input', { bubbles: true });
        }
        el.dispatchEvent(inputEvent);
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
      };
      let address = null;
      for (const selector of addressSelectors) {
        try {
          address = Array.from(document.querySelectorAll(selector)).find(visible);
          if (address) break;
        } catch (_) {}
      }
      if (!address) return false;
      const addressY = y(address);
      const candidates = Array.from(document.querySelectorAll('input,textarea'))
        .filter((el) => {
          if (!visible(el)) return false;
          if (el === address) return false;
          const tag = String(el.tagName || '').toLowerCase();
          const type = String(el.getAttribute('type') || '').toLowerCase();
          const autocomplete = String(el.getAttribute('autocomplete') || '').toLowerCase();
          const fieldY = y(el);
          if (fieldY >= addressY) return false;
          if (['hidden', 'checkbox', 'radio', 'button', 'submit', 'email', 'tel', 'number'].includes(type)) return false;
          if (/cc-|address-|postal|country|email|tel|phone/.test(autocomplete)) return false;
          return tag === 'textarea' || tag === 'input';
        })
        .sort((a, b) => (y(b) - y(a)) || (x(a) - x(b)));
      const target = candidates[0];
      if (!target) return false;
      setValue(target, name);
      return true;
    }"""

    address_selectors = [
        "#billingAddress-addressLine1Input",
        'input[name="addressLine1"]',
        'input[autocomplete="billing address-line1"]',
        'input[autocomplete="address-line1"]',
        'textarea[autocomplete="billing address-line1"]',
        'textarea[autocomplete="address-line1"]',
    ]
    page = getattr(api, "page", None)
    targets = [page] if page is not None else []
    targets.extend(getattr(page, "frames", []) or [])
    for target in targets:
        try:
            if target.evaluate(script, {"name": name, "addressSelectors": address_selectors}):
                logger.info("[bind_executor] 已通过 addressLine1 锚点补填账单全名")
                return None
        except Exception:
            continue
    logger.warning("[bind_executor] 未能通过 addressLine1 锚点补填账单全名")
    return None


def _nudge_billing_address_recalculation(api: ChatGPTTeamAPI, payload: dict[str, str]) -> None:
    """Force Stripe Address Element to publish the latest US address values.

    Stripe can visually show the updated country/address while its summary keeps
    the previous VAT until the Address Element emits another change/blur cycle.
    """

    script = r"""(fields) => {
      const visible = (el) => {
        if (!el || el.disabled || el.readOnly) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return el.getClientRects().length > 0;
      };
      const setValue = (el, value) => {
        if (!el) return false;
        el.scrollIntoView({ behavior: 'instant', block: 'center' });
        el.focus?.();
        const desired = String(value || '');
        const tag = String(el.tagName || '').toLowerCase();
        if (String(el.value || '') === desired) {
          el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
          el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
          el.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));
          el.blur?.();
          return true;
        }
        if (tag === 'select') {
          el.value = desired;
          el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
          el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
          el.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));
          el.blur?.();
          return true;
        }
        const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        if (descriptor?.set) descriptor.set.call(el, desired);
        else el.value = desired;
        let inputEvent;
        try {
          inputEvent = new InputEvent('input', {
            bubbles: true,
            composed: true,
            inputType: 'insertText',
            data: desired,
          });
        } catch (_) {
          inputEvent = new Event('input', { bubbles: true, composed: true });
        }
        el.dispatchEvent(inputEvent);
        el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));
        el.blur?.();
        return true;
      };
      const selectorMap = {
        name: ['#billingAddress-nameInput', 'input[name="name"]', 'input[autocomplete="billing name"]'],
        country: ['#billingAddress-countryInput', 'select[name="country"]', 'select[autocomplete="billing country"]'],
        address: ['#billingAddress-addressLine1Input', 'input[name="addressLine1"]', 'input[autocomplete="billing address-line1"]'],
        city: ['#billingAddress-localityInput', 'input[name="locality"]', 'input[autocomplete="billing address-level2"]'],
        state: ['#billingAddress-administrativeAreaInput', 'select[name="administrativeArea"]', 'input[name="administrativeArea"]', 'select[autocomplete="billing address-level1"]', 'input[autocomplete="billing address-level1"]'],
        postal_code: ['#billingAddress-postalCodeInput', 'input[name="postalCode"]', 'input[autocomplete="billing postal-code"]'],
      };
      const hasBillingAddressAnchor = selectorMap.address.some((selector) => {
        try {
          const candidates = Array.from(document.querySelectorAll(selector));
          return candidates.some(visible) || candidates.length > 0;
        } catch (_) {
          return false;
        }
      });
      if (!hasBillingAddressAnchor) return [];
      const changed = [];
      for (const [key, selectors] of Object.entries(selectorMap)) {
        const value = fields[key];
        if (!value) continue;
        let node = null;
        for (const selector of selectors) {
          try {
            const candidates = Array.from(document.querySelectorAll(selector));
            node = candidates.find(visible) || candidates[0] || null;
            if (node) break;
          } catch (_) {}
        }
        if (node && setValue(node, value)) changed.push(key);
      }
      try { document.activeElement?.blur?.(); } catch (_) {}
      return changed;
    }"""

    fields = {
        "name": str(payload.get("name") or ""),
        "country": str(payload.get("country") or "US"),
        "address": str(payload.get("address") or ""),
        "city": str(payload.get("city") or ""),
        "state": str(payload.get("state") or ""),
        "postal_code": str(payload.get("postal_code") or ""),
    }
    page = getattr(api, "page", None)
    changed_keys: set[str] = set()
    targets = [page] if page is not None else []
    targets.extend(getattr(page, "frames", []) or [])
    for target in targets:
        try:
            changed = target.evaluate(script, fields)
            if isinstance(changed, list):
                changed_keys.update(str(item) for item in changed)
        except Exception:
            continue
    if changed_keys:
        logger.info("[bind_executor] 已触发 Stripe 账单地址重算事件: %s", ",".join(sorted(changed_keys)))
    else:
        logger.warning("[bind_executor] 未找到可触发重算的 Stripe 账单地址字段")


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


def _compact_text(value: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _tax_summary_has_zero_tax(body_text: str) -> bool:
    text = str(body_text or "")
    normalized = re.sub(r"\s+", " ", text)
    has_zero_percent = bool(re.search(r"(?:tax|税额|税額)\s*\(\s*0%\s*\)", normalized, re.I))
    has_zero_amount = bool(re.search(r"(?:PHP|USD|US\$|\$|₱)\s*0[.,]00\b", normalized, re.I))
    return has_zero_percent and has_zero_amount


def _tax_summary_still_has_vat(body_text: str) -> bool:
    text = str(body_text or "")
    normalized = re.sub(r"\s+", " ", text)
    return bool(re.search(r"\bVAT\s*\(\s*[1-9]\d*(?:\.\d+)?%\s*\)", normalized, re.I))


def _wait_for_zero_tax_before_submit(
    api: ChatGPTTeamAPI,
    *,
    timeout_seconds: int = 45,
    is_cancelled=None,
):
    """Wait for Stripe/OpenAI checkout to recalculate tax after US billing address.

    PH/PHP checkout can initially show VAT (12%). After changing billing country
    to a US tax-free state, Stripe recalculates asynchronously and changes the
    summary to Tax/税额 (0%). Submitting before this refresh charges VAT.
    """

    deadline = time.time() + max(5, timeout_seconds)
    last_body = ""
    while time.time() < deadline:
        if callable(is_cancelled) and is_cancelled():
            return _build_result("failed", failure_stage="submit", message="任务已取消")

        body_text = _body_excerpt(api, limit=6000)
        last_body = body_text
        if _tax_summary_has_zero_tax(body_text):
            logger.info("[bind_executor] 税费已刷新为 0，允许继续提交")
            return None
        if not _tax_summary_still_has_vat(body_text):
            logger.info("[bind_executor] 未检测到非零 VAT，允许继续提交")
            return None

        logger.info("[bind_executor] 检测到 VAT 尚未归零，等待 Stripe 重新计算税费")
        time.sleep(3)

    return _build_result(
        "needs_review",
        failure_stage="submit",
        message=(
            "税费未在提交前刷新为 0，已停止自动提交；"
            f"页面摘要: {_compact_text(last_body, 260)}"
        ),
    )


def _wait_for_checkout_result(
    api: ChatGPTTeamAPI,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled=None,
    network_capture: dict | None = None,
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
            return _enrich_checkout_result_with_network_failure(classified, network_capture)

        time.sleep(3)

    _capture_screenshot(api, session_id, "timeout", screenshot_paths)
    return _enrich_checkout_result_with_network_failure(_build_result(
        "needs_review",
        failure_stage="post_submit",
        message="等待支付结果超时，需要人工确认最终状态",
        screenshot_paths=screenshot_paths,
    ), network_capture)


def run_bind_task(
    *,
    email: str = "",
    checkout_url: str,
    card_item: dict,
    proxy_url: str | None = None,
    proxy_bypass: str | None = None,
    use_roxybrowser: bool = True,
    roxybrowser_workspace_id: str = "",
    roxybrowser_profile_id: str = "",
    roxybrowser_auto_create_profile: bool = True,
    manual_confirm: bool = True,
    timeout_seconds: int = 900,
    is_cancelled=None,
):
    api = ChatGPTTeamAPI()
    session_id = uuid.uuid4().hex[:12]
    screenshot_paths: list[str] = []

    try:
        payload = extract_card_payload(card_item)
        auth_context = _selected_account_auth_context(email)
        if str(email or "").strip() and not _auth_context_has_web_session(auth_context):
            logger.warning("[bind_executor] 所选账号缺少可注入的 ChatGPT session token: %s", email)
            return _build_result(
                "failed",
                failure_stage="open_checkout",
                message=f"所选账号缺少可用 ChatGPT session token: {email}",
            )
        billing_address = generate_tax_free_billing_address()
        payload["name"] = payload["name"] or billing_address.get("name", "")
        payload["country"] = billing_address.get("country", "US")
        payload["address"] = billing_address.get("address1", "")
        payload["city"] = billing_address.get("city", "")
        payload["state"] = billing_address.get("state", "")
        payload["postal_code"] = billing_address.get("zip", "")
        logger.info(
            "[bind_executor] 使用免税州账单地址: state=%s city=%s zip=%s",
            payload["state"],
            payload["city"],
            payload["postal_code"],
        )
        device_id = str(auth_context.get("device_id") or "").strip()
        if device_id:
            api.oai_device_id = device_id
        api._launch_browser(
            proxy_url=proxy_url,
            proxy_bypass=proxy_bypass,
            background=False if manual_confirm else None,
            randomize_fingerprint=False,
            locale="zh-CN",
            accept_language="zh-CN,zh;q=0.9,en;q=0.8",
            use_roxybrowser=bool(use_roxybrowser),
            roxybrowser_workspace_id=str(roxybrowser_workspace_id or "").strip() or None,
            roxybrowser_profile_id=None
            if bool(roxybrowser_auto_create_profile)
            else (str(roxybrowser_profile_id or "").strip() or None),
            roxybrowser_force_new_profile=bool(roxybrowser_auto_create_profile),
        )
        injected_login_state = _inject_selected_account_auth_session(api, auth_context, email)
        if not injected_login_state and str(email or "").strip():
            return _build_result(
                "failed",
                failure_stage="open_checkout",
                message=f"所选账号缺少可用 ChatGPT session token: {email}",
            )
        if injected_login_state:
            _warm_chatgpt_login_state_page(api)

        if callable(is_cancelled) and is_cancelled():
            return _build_result("failed", failure_stage="open_checkout", message="任务已取消")

        try:
            _open_checkout_from_fresh_payment_page(api, checkout_url)
        except Exception as exc:
            _capture_screenshot(api, session_id, "open-checkout-failed", screenshot_paths)
            return _build_result(
                "failed",
                failure_stage="open_checkout",
                message=f"打开 checkout 页面失败: {exc}",
                screenshot_paths=screenshot_paths,
            )

        network_capture = _new_checkout_network_capture()
        _install_checkout_network_capture(api, network_capture)
        api._wait_for_cloudflare()
        _capture_screenshot(api, session_id, "opened", screenshot_paths)

        for selectors, value, label, required in (
            (CARD_NUMBER_SELECTORS, payload["card_number"], "卡号", True),
            (EXPIRY_SELECTORS, payload["expiry_date"], "有效期", True),
            (CVC_SELECTORS, payload["cvv"], "CVV", True),
        ):
            field_timeout_ms = CARD_NUMBER_WAIT_TIMEOUT_MS if selectors == CARD_NUMBER_SELECTORS else PAYMENT_FIELD_WAIT_TIMEOUT_MS
            result = _fill_field(api, selectors, value, label, required=required, timeout_ms=field_timeout_ms)
            if result:
                result["screenshot_paths"] = screenshot_paths
                _capture_screenshot(api, session_id, "fill-card-failed", screenshot_paths)
                return result

        # Stripe/Link 的账单区经常在卡字段填完后才二次渲染。
        # 参考插件做法：再用固定字段选择器补填一次账单区。
        time.sleep(1.5)
        for selectors, value, label in (
            (BILLING_NAME_SELECTORS, payload["name"], "账单全名"),
            (COUNTRY_SELECTORS, payload["country"], "国家"),
            (ADDRESS_SELECTORS, payload["address"], "账单地址"),
            (CITY_SELECTORS, payload["city"], "城市"),
            (STATE_SELECTORS, payload["state"], "州/省"),
            (POSTAL_CODE_SELECTORS, payload["postal_code"], "邮编"),
        ):
            result = _fill_field(
                api,
                selectors,
                value,
                label,
                required=False,
                timeout_ms=PAYMENT_FIELD_WAIT_TIMEOUT_MS,
            )
            if result:
                result["screenshot_paths"] = screenshot_paths
                _capture_screenshot(api, session_id, "fill-billing-failed", screenshot_paths)
                return result

        _nudge_billing_address_recalculation(api, payload)
        time.sleep(2)
        tax_wait_result = _wait_for_zero_tax_before_submit(
            api,
            timeout_seconds=45,
            is_cancelled=is_cancelled,
        )
        if tax_wait_result:
            tax_wait_result["screenshot_paths"] = screenshot_paths
            _capture_screenshot(api, session_id, "tax-not-zero", screenshot_paths)
            return tax_wait_result

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
                network_capture=network_capture,
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
            network_capture=network_capture,
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
