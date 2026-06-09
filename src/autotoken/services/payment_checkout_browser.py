"""Shared browser helpers for ChatGPT checkout pages."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BodyExcerpt = Callable[[Any, int], str]
PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS = (
    "#captcha-standalone",
    ".captcha-overlay",
    ".captcha-container",
)


def _safe_text(value: Any, *, limit: int = 300) -> str:
    text = str(value or "")
    return text[:limit]


def iter_page_frames(api: Any) -> list[Any]:
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


def dismiss_address_autocomplete(
    api: Any,
    address1_locator=None,
    *,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    try:
        if address1_locator:
            address1_locator.evaluate(
                """(el) => {
                  el.setAttribute('autocomplete', 'off');
                  el.setAttribute('aria-autocomplete', 'none');
                  if (typeof el.blur === 'function') el.blur();
                }""",
                timeout=800,
            )
    except Exception:
        pass
    try:
        if address1_locator:
            try:
                address1_locator.press("Escape", timeout=800)
            except Exception:
                pass
        api.page.keyboard.press("Escape")
        sleep(0.2)
        if not getattr(api, "_address_autocomplete_dismiss_logged", False):
            if logger:
                logger.info("%s 已关闭地址自动推荐，改为手动填写城市/州/邮编", log_prefix)
            api._address_autocomplete_dismiss_logged = True
    except Exception as exc:
        if logger:
            logger.debug("%s 关闭地址自动推荐失败: %s", log_prefix, exc)


def click_first_visible(
    selectors: list[str],
    *,
    visible_locator: Callable[[list[str], int], Any],
    timeout_ms: int = 2000,
) -> bool:
    locator = visible_locator(selectors, timeout_ms)
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


def locator_is_checked(locator: Any) -> bool:
    try:
        return bool(locator.is_checked(timeout=500))
    except Exception:
        pass
    try:
        checked_raw = locator.get_attribute("checked", timeout=300)
        checked_attr = str(checked_raw or "").strip().lower()
        if checked_raw is not None and checked_attr in {"", "true", "checked"}:
            tag_name = str(locator.evaluate("el => el.tagName", timeout=300) or "").lower()
            if tag_name == "input":
                checked = locator.evaluate("el => Boolean(el.checked)", timeout=300)
                if checked is not None:
                    return bool(checked)
        if checked_raw is not None:
            return checked_attr in {"true", "checked"}
    except Exception:
        pass
    try:
        return str(locator.get_attribute("aria-checked", timeout=300) or "").strip().lower() == "true"
    except Exception:
        return False


def paypal_option_selected(
    api: Any,
    *,
    state_selectors: list[str],
    attached_locator: Callable[[list[str], int], Any],
    locator_checked: Callable[[Any], bool] = locator_is_checked,
    timeout_ms: int = 300,
) -> bool:
    locator = attached_locator(state_selectors, timeout_ms)
    if locator and locator_checked(locator):
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


def click_paypal_checkout_control(
    api: Any,
    *,
    checkout_selectors: list[str],
    state_selectors: list[str],
    click_first: Callable[[list[str], int], bool],
    attached_locator: Callable[[list[str], int], Any],
    frames: Callable[[Any], list[Any]] = iter_page_frames,
) -> bool:
    if click_first(checkout_selectors, 2500):
        return True
    locator = attached_locator(state_selectors, 400)
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
    for frame in frames(api):
        try:
            if bool(frame.evaluate(text_row_script)):
                return True
        except Exception:
            continue
    return False


def select_paypal_option(
    api: Any,
    *,
    paypal_host: Callable[[str], bool],
    option_selected: Callable[[Any], bool],
    click_control: Callable[[Any], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> bool:
    if paypal_host(getattr(api.page, "url", "")):
        return True
    if option_selected(api):
        if on_progress:
            on_progress(progress_event("paypal_option_selected", url=getattr(api.page, "url", "")))
        return True
    for _ in range(attempts):
        clicked = click_control(api)
        sleep(0.8)
        if paypal_host(getattr(api.page, "url", "")) or option_selected(api):
            if on_progress:
                on_progress(progress_event("paypal_option_selected", url=getattr(api.page, "url", "")))
            return True
        if not clicked:
            sleep(0.4)
    return False


def wait_paypal_checkout_interactive(
    api: Any,
    *,
    paypal_selectors: list[str],
    submit_selectors: list[str],
    visible_locator: Callable[[list[str], int], Any],
    body_excerpt: BodyExcerpt,
    timeout_seconds: int = 45,
    logger: logging.Logger | None = None,
    url_summary: Callable[[str], str] = str,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = now() + max(5, timeout_seconds)
    while now() < deadline:
        if visible_locator(paypal_selectors, 800):
            return True
        if visible_locator(submit_selectors, 500):
            return True
        body_text = body_excerpt(api, 2000).strip()
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
            sleep(1.0)
    if logger:
        logger.info(
            "[paypal_bind_executor] checkout page not interactive: url=%s body=%s",
            url_summary(getattr(api.page, "url", "")),
            body_excerpt(api, 500),
        )
    return False


def inspect_paypal_page(
    api: Any,
    *,
    paypal_host: Callable[[str], bool],
    ensure_captcha_bypass: Callable[[Any], bool],
    body_excerpt: BodyExcerpt,
    visible_locator: Callable[[list[str], int], Any],
    has_phone_rejected_prompt: Callable[[Any], bool],
    has_otp_inputs: Callable[[Any], bool],
    phone_rejected_text_hint: Callable[[str], bool],
    card_rejected_text_hint: Callable[[str], bool],
    signup_registration_text_hint: Callable[[str], bool],
    signup_otp_text_hint: Callable[..., bool],
    login_text_hint: Callable[[str], bool],
    passkey_text_hint: Callable[[str], bool],
    approve_text_hint: Callable[[str], bool],
    email_selectors: list[str],
    password_selectors: list[str],
    approve_selectors: list[str],
    prompt_selectors: list[str],
    create_account_selectors: list[str],
    phone_selectors: list[str],
    card_selectors: list[str],
) -> dict[str, Any]:
    current_url = getattr(api.page, "url", "")
    body_text = body_excerpt(api, 8000)
    is_paypal_page = paypal_host(current_url)
    if is_paypal_page:
        ensure_captcha_bypass(api)
    phone_rejected_prompt = has_phone_rejected_prompt(api) if is_paypal_page else False
    if phone_rejected_prompt and not phone_rejected_text_hint(body_text):
        body_text = f"{body_text}\nTry a different phone number"
    card_rejected_prompt = is_paypal_page and card_rejected_text_hint(body_text)

    email_locator = visible_locator(email_selectors, 400)
    password_locator = visible_locator(password_selectors, 400)
    approve_locator = visible_locator(approve_selectors, 400)
    prompt_locator = visible_locator(prompt_selectors, 400)
    create_account_locator = visible_locator(create_account_selectors, 400)
    phone_locator = visible_locator(phone_selectors, 400)
    card_locator = visible_locator(card_selectors, 400)
    otp_inputs_ready = has_otp_inputs(api) if is_paypal_page else False
    registration_text_hint = is_paypal_page and signup_registration_text_hint(body_text)

    login_phase = ""
    if email_locator and password_locator:
        login_phase = "login_combined"
    elif email_locator:
        login_phase = "email"
    elif password_locator:
        login_phase = "password"

    needs_login = is_paypal_page and (bool(email_locator or password_locator) or login_text_hint(body_text))
    has_passkey_prompt = is_paypal_page and (bool(prompt_locator) or passkey_text_hint(body_text))
    approve_ready = is_paypal_page and (bool(approve_locator) or approve_text_hint(body_text))
    registration_inputs_ready = bool(card_locator or phone_locator or registration_text_hint)
    otp_text_hint = signup_otp_text_hint(body_text, loose=True)
    if otp_text_hint:
        otp_inputs_ready = True
    needs_otp = is_paypal_page and (otp_inputs_ready or otp_text_hint)
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


def dismiss_paypal_prompts(
    api: Any,
    *,
    prompt_selectors: list[str],
    click_first: Callable[[list[str], int], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    if click_first(prompt_selectors, 1500):
        if on_progress:
            on_progress(progress_event("paypal_prompt_dismissed", url=getattr(api.page, "url", "")))
        return True
    return False


def paypal_signup_registration_form_visible(
    api: Any,
    *,
    body_excerpt: BodyExcerpt,
    text_visible: Callable[[str], bool],
    visible_locator: Callable[[list[str], int], Any],
    field_selector_groups: list[list[str]] | tuple[list[str], ...],
) -> bool:
    text = body_excerpt(api, 12000)
    if text_visible(text):
        return True
    try:
        visible_fields = sum(1 for selectors in field_selector_groups if visible_locator(selectors, 250) is not None)
        return visible_fields >= 2
    except Exception:
        return False


def click_paypal_create_account(
    api: Any,
    *,
    create_account_selectors: list[str],
    click_first: Callable[[list[str], int], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    if click_first(create_account_selectors, 2000):
        if on_progress:
            on_progress(progress_event("paypal_create_account", url=getattr(api.page, "url", "")))
        return True
    return False


def maybe_enter_paypal_signup_from_login(
    api: Any,
    *,
    state: dict[str, Any],
    signup_submitted: bool,
    signup_email_submitted: bool,
    ba_token: str,
    country: str,
    lang: str,
    click_create_account: Callable[[Any], bool],
    goto_create_account_entry: Callable[..., bool],
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool] | None:
    if not (
        state.get("needs_login")
        and not signup_submitted
        and not signup_email_submitted
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_otp")
        and not state.get("approve_ready")
    ):
        return None
    if state.get("create_account_ready") and click_create_account(api):
        sleep(2.0)
        return True, "", True
    if goto_create_account_entry(
        api,
        ba_token=ba_token or str(state.get("ba_token") or ""),
        country=country,
        lang=lang,
    ):
        return True, "", True
    return True, "", False


def handle_paypal_signup_needs_login_redirect(
    api: Any,
    *,
    state: dict[str, Any],
    signup_login_redirect_count: int,
    max_redirects: int,
    ba_token: str,
    country: str,
    lang: str,
    goto_create_account_entry: Callable[..., bool],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep_after_redirect_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if not state.get("needs_login"):
        return None

    if signup_login_redirect_count < max_redirects and goto_create_account_entry(
        api,
        ba_token=ba_token,
        country=country,
        lang=lang,
        on_progress=on_progress,
    ):
        if sleep_after_redirect_seconds > 0:
            sleep(sleep_after_redirect_seconds)
        return {
            "action": "continue",
            "signup_login_redirect_count": signup_login_redirect_count + 1,
            "signup_email_submitted": False,
            "signup_email_submitted_at": 0.0,
            "signup_form_submitted": False,
            "signup_submitted_at": 0.0,
        }

    return {
        "action": "failed",
        "screenshot_label": "paypal-signup-login-page",
        "message": "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单",
    }


def maybe_dismiss_paypal_passkey_prompt(
    api: Any,
    *,
    state: dict[str, Any],
    dismiss_prompts: Callable[..., bool],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    if not (state.get("has_passkey_prompt") and not state.get("needs_otp")):
        return False
    if not dismiss_prompts(api, on_progress=on_progress):
        return False
    sleep(1.2)
    return True


def maybe_click_paypal_signup_create_account_ready(
    api: Any,
    *,
    state: dict[str, Any],
    click_create_account: Callable[[Any], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool] | None:
    if not (
        state.get("create_account_ready")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_otp")
    ):
        return None
    if not click_create_account(api):
        return None
    sleep(2.0)
    return True, "", True


def seed_paypal_signup_authorize_state(
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
    state["signup_email_submitted"] = signup_email_submitted
    state["signup_email_submitted_at"] = signup_email_submitted_at
    state["signup_submitted"] = signup_form_submitted
    state["signup_submitted_at"] = signup_submitted_at
    state["submitted_phone_keys"] = submitted_phone_keys
    state["phone_only_retry"] = phone_only_retry
    state["card_retry_count"] = card_retry_count
    state["otp_phone_lock_key"] = otp_phone_lock_key
    return state


def sync_paypal_signup_authorize_state(
    state: dict[str, Any],
    *,
    signup_email_submitted: bool,
    signup_email_submitted_at: float,
    signup_form_submitted: bool,
    signup_submitted_at: float,
    card_retry_count: int,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    if bool(state.get("signup_email_submitted")) and not signup_email_submitted:
        signup_email_submitted_at = float(state.get("signup_email_submitted_at") or now())
        signup_email_submitted = True
    elif bool(state.get("signup_email_submitted")) and signup_email_submitted:
        state_submitted_at = float(state.get("signup_email_submitted_at") or 0)
        if state_submitted_at > 0:
            signup_email_submitted_at = state_submitted_at
    elif not bool(state.get("signup_email_submitted")) and signup_email_submitted:
        signup_email_submitted = False
        signup_email_submitted_at = 0.0

    if bool(state.get("signup_submitted")) and not signup_form_submitted:
        signup_submitted_at = float(state.get("signup_submitted_at") or now())
        signup_form_submitted = True
    elif bool(state.get("signup_submitted_at")):
        signup_submitted_at = float(state.get("signup_submitted_at") or signup_submitted_at)

    return {
        "signup_email_submitted": signup_email_submitted,
        "signup_email_submitted_at": signup_email_submitted_at,
        "signup_form_submitted": signup_form_submitted,
        "signup_submitted_at": signup_submitted_at,
        "phone_only_retry": bool(state.get("phone_only_retry")),
        "card_retry_count": int(state.get("card_retry_count") or card_retry_count),
        "otp_phone_lock_key": str(state.get("otp_phone_lock_key") or ""),
    }


def paypal_signup_authorize_state_values(
    signup_state: dict[str, Any],
) -> tuple[bool, float, bool, float, bool, int, str]:
    return (
        bool(signup_state["signup_email_submitted"]),
        float(signup_state["signup_email_submitted_at"]),
        bool(signup_state["signup_form_submitted"]),
        float(signup_state["signup_submitted_at"]),
        bool(signup_state["phone_only_retry"]),
        int(signup_state["card_retry_count"]),
        str(signup_state["otp_phone_lock_key"]),
    )


PAYPAL_SIGNUP_RECOVER_STATE_KEYS = (
    "_email_stuck_recover_count",
    "_email_reload_cycle_count",
    "_email_first_submitted_at",
    "_fill_retry_count",
)


def merge_paypal_inspected_state(
    previous_state: dict[str, Any] | None,
    inspected_state: dict[str, Any],
    *,
    ba_token: str = "",
    recover_keys: tuple[str, ...] = PAYPAL_SIGNUP_RECOVER_STATE_KEYS,
) -> dict[str, Any]:
    state = dict(inspected_state or {})
    if isinstance(previous_state, dict):
        for key in recover_keys:
            if key in previous_state:
                state[key] = previous_state[key]
    if ba_token:
        state["ba_token"] = ba_token
    return state


def paypal_signup_email_step_state(
    state: dict[str, Any],
    *,
    signup_email_submitted: bool,
    wait_timeout_seconds: float,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    is_email_step = bool(
        state.get("email_locator") and not state.get("registration_ready") and not state.get("registration_text_hint")
    )
    is_blank_after_email = bool(
        signup_email_submitted
        and not state.get("email_locator")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_login")
        and not state.get("needs_otp")
        and not state.get("approve_ready")
    )
    result: dict[str, Any] = {
        "is_email_step": is_email_step,
        "is_blank_after_email": is_blank_after_email,
        "submitted_at": 0.0,
        "first_submitted_at": 0.0,
        "timeout_result": None,
    }
    if not ((is_email_step or is_blank_after_email) and signup_email_submitted):
        return result

    submitted_at = float(state.get("signup_email_submitted_at") or 0)
    first_submitted_at = float(state.get("_email_first_submitted_at") or submitted_at)
    if not state.get("_email_first_submitted_at") and submitted_at > 0:
        state["_email_first_submitted_at"] = submitted_at
    result["submitted_at"] = submitted_at
    result["first_submitted_at"] = first_submitted_at
    if first_submitted_at > 0 and now() - first_submitted_at > wait_timeout_seconds:
        result["timeout_result"] = (False, "等待 PayPal 注册表单加载超时", False)
    return result


def recover_paypal_signup_email_step(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    submitted_at: float,
    first_submitted_at: float,
    stuck_recover_delay_seconds: float,
    recover_email_spinner: Callable[[Any, str], dict[str, Any]],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    logger: logging.Logger | None = None,
    max_js_before_reload: int = 1,
    max_reload_cycles: int = 3,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool] | None:
    elapsed = now() - submitted_at if submitted_at > 0 else 0
    js_count = int(state.get("_email_stuck_recover_count") or 0)
    reload_cycles = int(state.get("_email_reload_cycle_count") or 0)

    if not (
        elapsed > stuck_recover_delay_seconds
        and (js_count <= max_js_before_reload or reload_cycles < max_reload_cycles)
    ):
        return None

    if js_count < max_js_before_reload:
        state["_email_stuck_recover_count"] = js_count + 1
        recover_email = str(signup_profile.get("email") or "").strip()
        if logger:
            logger.info(
                "[paypal_signup] page stuck after email submit (%.0fs), JS recover attempt %d...",
                elapsed,
                js_count + 1,
            )
        if on_progress:
            on_progress(
                progress_event(
                    "paypal_signup_email_reload",
                    f"邮箱提交后页面卡住，正在 JS 恢复 ({js_count + 1}/{max_js_before_reload})",
                )
            )
        recover_result = recover_email_spinner(api, recover_email)
        if logger:
            logger.info("[paypal_signup] JS recover result: %s", recover_result)
        if not recover_result.get("recovered"):
            state["signup_email_submitted"] = False
            state["signup_email_submitted_at"] = 0
        sleep(2.0)
        return True, "", True

    if reload_cycles < max_reload_cycles:
        reload_cycles += 1
        state["_email_reload_cycle_count"] = reload_cycles
        state["_email_stuck_recover_count"] = 0
        state["_email_first_submitted_at"] = 0
        state["signup_email_submitted"] = False
        state["signup_email_submitted_at"] = 0
        state["_fill_retry_count"] = 0
        if logger:
            logger.info(
                "[paypal_signup] SPA deadlocked after JS attempts, reload cycle %d/%d (%.0fs total)...",
                reload_cycles,
                max_reload_cycles,
                now() - first_submitted_at,
            )
        if on_progress:
            on_progress(
                progress_event(
                    "paypal_signup_email_reload",
                    f"邮箱提交后 SPA 死锁，正在刷新页面重试 (第 {reload_cycles}/{max_reload_cycles} 轮)",
                )
            )
        try:
            api.page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        sleep(3.0)
        return True, "", True

    return None


def continue_paypal_signup_email_step(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    current_url: str,
    signup_email_submitted: bool,
    is_blank_after_email: bool,
    submit_email_step: Callable[..., tuple[bool, str]],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool]:
    if signup_email_submitted:
        if on_progress:
            on_progress(
                progress_event(
                    "paypal_wait_signup_form",
                    url=current_url,
                    email=str(signup_profile.get("email") or ""),
                )
            )
        sleep(1.5)
        return True, "", True
    if is_blank_after_email:
        sleep(1.5)
        return True, "", True
    ok, error = submit_email_step(
        api,
        signup_profile=signup_profile,
        state=state,
        on_progress=on_progress,
    )
    if ok:
        state["signup_email_submitted"] = True
        state["signup_email_submitted_at"] = now()
    return ok, error, True


def recover_paypal_signup_unhandled_email_stuck(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    signup_email_submitted: bool,
    signup_email_submitted_at: float,
    current_url: str,
    wait_timeout_seconds: float,
    stuck_recover_delay_seconds: float,
    recover_email_spinner: Callable[[Any, str], dict[str, Any]],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    logger: logging.Logger | None = None,
    url_summary: Callable[[str], str] = str,
    max_js_before_reload: int = 1,
    max_reload_cycles: int = 3,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if signup_email_submitted and logger:
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
            now() - signup_email_submitted_at if signup_email_submitted_at > 0 else 0,
            url_summary(current_url),
        )

    if not (
        signup_email_submitted
        and not state.get("needs_login")
        and not state.get("email_locator")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_otp")
        and not state.get("approve_ready")
    ):
        return None

    first_submitted_at = float(state.get("_email_first_submitted_at") or signup_email_submitted_at)
    current_time = now()
    if first_submitted_at > 0 and current_time - first_submitted_at > wait_timeout_seconds:
        return {
            "action": "failed",
            "screenshot_label": "paypal-signup-email-timeout",
            "message": "等待 PayPal 注册表单加载超时",
        }

    stuck_elapsed = current_time - signup_email_submitted_at if signup_email_submitted_at > 0 else 0
    js_count = int(state.get("_email_stuck_recover_count") or 0)
    reload_cycles = int(state.get("_email_reload_cycle_count") or 0)
    if not (
        stuck_elapsed > stuck_recover_delay_seconds
        and (js_count <= max_js_before_reload or reload_cycles < max_reload_cycles)
    ):
        return None

    if js_count < max_js_before_reload:
        state["_email_stuck_recover_count"] = js_count + 1
        recover_email = str(signup_profile.get("email") or "").strip()
        if logger:
            logger.info(
                "[paypal_authorize] page stuck (%.0fs, %.0fs total), JS recover %d...",
                stuck_elapsed,
                current_time - first_submitted_at,
                js_count + 1,
            )
        if on_progress:
            on_progress(
                progress_event(
                    "paypal_signup_email_reload",
                    f"邮箱提交后页面卡住（无表单元素），JS 恢复 ({js_count + 1}/{max_js_before_reload})",
                )
            )
        recover_result = recover_email_spinner(api, recover_email)
        if logger:
            logger.info("[paypal_authorize] JS recover result: %s", recover_result)
        if not recover_result.get("recovered"):
            state["signup_email_submitted"] = False
            state["signup_email_submitted_at"] = 0
            signup_email_submitted = False
            signup_email_submitted_at = 0.0
        sleep(2.0)
        return {
            "action": "continue",
            "signup_email_submitted": signup_email_submitted,
            "signup_email_submitted_at": signup_email_submitted_at,
        }

    if reload_cycles < max_reload_cycles:
        reload_cycles += 1
        state["_email_reload_cycle_count"] = reload_cycles
        state["_email_stuck_recover_count"] = 0
        state["_email_first_submitted_at"] = 0
        state["signup_email_submitted"] = False
        state["signup_email_submitted_at"] = 0
        state["_fill_retry_count"] = 0
        if logger:
            logger.info(
                "[paypal_authorize] SPA deadlocked, reload cycle %d/%d (%.0fs total)...",
                reload_cycles,
                max_reload_cycles,
                current_time - first_submitted_at,
            )
        if on_progress:
            on_progress(
                progress_event(
                    "paypal_signup_email_reload",
                    f"SPA 死锁，正在刷新页面重试 (第 {reload_cycles}/{max_reload_cycles} 轮)",
                )
            )
        try:
            api.page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        sleep(3.0)
        return {
            "action": "continue",
            "signup_email_submitted": False,
            "signup_email_submitted_at": 0.0,
        }

    return None


def maybe_mark_paypal_signup_registration_ready(
    api: Any,
    *,
    state: dict[str, Any],
    signup_submitted: bool,
    registration_form_visible: Callable[[Any], bool],
) -> bool:
    if (
        not signup_submitted
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and registration_form_visible(api)
    ):
        state["registration_ready"] = True
        state["registration_text_hint"] = True
        return True
    return False


def stop_before_paypal_signup_otp(
    *,
    state: dict[str, Any],
    signup_profile: dict[str, Any],
    current_url: str,
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[bool, str, bool]:
    state["_stop_before_signup_otp"] = True
    if on_progress:
        on_progress(
            progress_event(
                "paypal_wait_signup_otp",
                "PayPal 注册表单已提交，已在手机验证码输入前停止",
                url=current_url,
                otp_channel=str(signup_profile.get("otp_channel") or "sms"),
                phone=str(signup_profile.get("phone") or ""),
            )
        )
    return True, "", False


def handle_paypal_signup_submitted_phase(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    card_retry_count: int,
    current_url: str,
    is_cancelled=None,
    visible_validation_error: Callable[[Any], str],
    release_phone_lock: Callable[..., None],
    retry_card_rejected: Callable[..., tuple[bool, str, bool]],
    stop_before_signup_otp_enabled: Callable[[], bool],
    body_excerpt: BodyExcerpt,
    has_otp_inputs: Callable[[Any], bool],
    signup_otp_text_hint: Callable[[str], bool],
    stop_before_otp: Callable[..., tuple[bool, str, bool]],
    maybe_wait_for_otp: Callable[..., tuple[bool, str, bool] | None],
    submit_otp: Callable[..., tuple[bool, str, bool]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool]:
    validation_error = visible_validation_error(api)
    if validation_error:
        release_phone_lock(state, on_progress=on_progress)
        return False, f"PayPal 注册表单校验失败: {validation_error}", True

    if state.get("card_rejected"):
        return retry_card_rejected(
            api,
            signup_profile=signup_profile,
            state=state,
            card_retry_count=card_retry_count,
            current_url=current_url,
            on_progress=on_progress,
        )

    if stop_before_signup_otp_enabled():
        for _ in range(10):
            excerpt = body_excerpt(api).lower()
            if has_otp_inputs(api) or signup_otp_text_hint(excerpt):
                break
            sleep(0.5)
        return stop_before_otp(
            state=state,
            signup_profile=signup_profile,
            current_url=current_url,
            on_progress=on_progress,
        )

    otp_wait_result = maybe_wait_for_otp(
        api,
        state=state,
        signup_profile=signup_profile,
        current_url=current_url,
        on_progress=on_progress,
    )
    if otp_wait_result is not None:
        return otp_wait_result

    if stop_before_signup_otp_enabled():
        return stop_before_otp(
            state=state,
            signup_profile=signup_profile,
            current_url=current_url,
            on_progress=on_progress,
        )

    return submit_otp(
        api,
        signup_profile=signup_profile,
        state=state,
        current_url=current_url,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
    )


def maybe_wait_for_paypal_signup_otp(
    api: Any,
    *,
    state: dict[str, Any],
    signup_profile: dict[str, Any],
    current_url: str,
    otp_wait_timeout_seconds: float,
    body_excerpt: BodyExcerpt,
    has_otp_inputs: Callable[[Any], bool],
    signup_otp_text_hint: Callable[[str], bool],
    click_create_submit: Callable[[Any], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    logger: logging.Logger | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool] | None:
    if not state.get("otp_inputs_ready") and not state.get("needs_otp"):
        excerpt = body_excerpt(api, 8000).lower()
        if has_otp_inputs(api) or signup_otp_text_hint(excerpt):
            state["otp_inputs_ready"] = True
            state["needs_otp"] = True
        else:
            state["_last_signup_otp_wait_excerpt"] = excerpt[:500]
    if state.get("otp_inputs_ready") or state.get("needs_otp"):
        return None

    submitted_at = float(state.get("signup_submitted_at") or 0)
    if submitted_at > 0 and now() - submitted_at > otp_wait_timeout_seconds:
        return False, "等待 PayPal 验证码超时", False
    if (
        state.get("approve_ready")
        and not state.get("registration_ready")
        and not state.get("registration_text_hint")
        and not state.get("needs_otp")
    ):
        if logger:
            logger.info(
                "[paypal_signup] approve_ready after OTP, attempting PAYPAL_CREATE_SUBMIT click, url=%s",
                current_url,
            )
        if click_create_submit(api):
            if on_progress:
                on_progress(progress_event("paypal_agree_create_clicked", url=current_url))
            if logger:
                logger.info("[paypal_signup] Agree & Create Account clicked, waiting for navigation")
            try:
                api.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            sleep(3.0)
            return True, "", True
        if logger:
            logger.info("[paypal_signup] PAYPAL_CREATE_SUBMIT not found, falling back to authorize flow")
        return True, "", False

    if on_progress:
        on_progress(
            progress_event(
                "paypal_wait_signup_otp",
                url=current_url,
                otp_channel=str(signup_profile.get("otp_channel") or "sms"),
                phone=str(signup_profile.get("phone") or ""),
            )
        )
    sleep(1.5)
    return True, "", True


def submit_paypal_signup_otp(
    api: Any,
    *,
    signup_profile: dict[str, Any],
    state: dict[str, Any],
    current_url: str,
    otp_poll_timeout_seconds: int,
    is_cancelled=None,
    poll_signup_otp: Callable[..., str],
    fill_otp_inputs: Callable[[Any, str], bool],
    click_next: Callable[[Any], bool],
    release_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    otp_cancelled_exception: Any = Exception,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str, bool]:
    try:
        otp = poll_signup_otp(
            api=api,
            signup_profile=signup_profile,
            timeout_seconds=otp_poll_timeout_seconds,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )
    except otp_cancelled_exception as exc:
        return False, f"等待 PayPal OTP 超时: {exc}", False
    if not fill_otp_inputs(api, otp):
        return False, "未找到 PayPal 验证码输入框", False
    if on_progress:
        on_progress(progress_event("paypal_submit_otp", url=current_url))
    if not click_next(api):
        try:
            api.page.keyboard.press("Enter")
        except Exception:
            return False, "未找到 PayPal 验证码提交按钮", False
    release_phone_lock(state, on_progress=on_progress)
    sleep(2.0)
    return True, "", True


def paypal_signup_email_step_advanced(
    api: Any,
    before_url: str,
    *,
    sync_payment_page: Callable[..., Any],
    is_pay_entry_url: Callable[[str], bool],
    inspect_page: Callable[[Any], dict[str, Any]],
) -> bool:
    sync_payment_page(api, prefer_paypal=True)
    current_url = str(getattr(api.page, "url", "") or "")
    if current_url and current_url != before_url:
        return True
    if is_pay_entry_url(before_url) and not is_pay_entry_url(current_url):
        return True
    state = inspect_page(api)
    return bool(state.get("registration_ready") or state.get("registration_text_hint") or state.get("needs_otp"))


def wait_paypal_signup_email_step_advanced(
    api: Any,
    before_url: str,
    *,
    step_advanced: Callable[[Any, str], bool],
    timeout_seconds: float = 8.0,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = now() + max(1.0, float(timeout_seconds))
    while now() < deadline:
        if step_advanced(api, before_url):
            return True
        try:
            api.page.wait_for_timeout(400)
        except Exception:
            sleep(0.4)
    return step_advanced(api, before_url)


def js_click_paypal_signup_email_submit(
    api: Any,
    *,
    frames: Callable[[Any], list[Any]] = iter_page_frames,
    logger: logging.Logger | None = None,
) -> bool:
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
    for frame in frames(api):
        try:
            result = frame.evaluate(script)
            if isinstance(result, dict) and result.get("clicked"):
                if logger:
                    logger.info("[paypal_signup] JS email submit clicked: %s", result.get("text"))
                return True
            if result is True:
                return True
        except Exception:
            continue
    return False


def js_recover_paypal_email_spinner(api: Any, email: str) -> dict[str, Any]:
    script = r"""
    (email) => {
      const result = {recovered: false, detail: '', spinners_removed: 0, submit_clicked: false};
      try {
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
              if (node.id && /captcha/i.test(node.id)) return;
              if (node.className && /captcha/i.test(String(node.className))) return;
              node.remove();
              result.spinners_removed++;
            } catch(e) {}
          });
        });

        document.querySelectorAll('[disabled], [aria-disabled="true"], [aria-busy="true"]').forEach(node => {
          try {
            node.removeAttribute('disabled');
            node.removeAttribute('aria-disabled');
            node.removeAttribute('aria-busy');
          } catch(e) {}
        });

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
          submitBtn = controls.find(n => n.getAttribute('type') === 'submit');
        }
        if (submitBtn) {
          submitBtn.removeAttribute('disabled');
          submitBtn.removeAttribute('aria-disabled');
          submitBtn.click();
          result.submit_clicked = true;
          result.detail += 'btn_clicked:' + textOf(submitBtn).slice(0, 40) + ';';
        } else {
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


def inspect_paypal_email_gate(api: Any) -> dict[str, Any]:
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


def submit_paypal_signup_email_step(
    api: Any,
    *,
    signup_profile: dict[str, str | bool],
    state: dict[str, Any],
    submit_selectors: list[str],
    set_locator_value: Callable[[Any, str], bool],
    click_first: Callable[[list[str], int], bool],
    wait_step_advanced: Callable[[Any, str], bool],
    js_click_submit: Callable[[Any], bool],
    inspect_gate: Callable[[Any], dict[str, Any]],
    body_excerpt: BodyExcerpt,
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    logger: logging.Logger | None = None,
    url_summary: Callable[[str], str] = str,
    compact_log_text: Callable[..., str] = _safe_text,
) -> tuple[bool, str]:
    email = str(signup_profile.get("email") or "").strip()
    if not email:
        return False, "PayPal 注册邮箱为空"
    email_locator = state.get("email_locator")
    if not email_locator:
        return False, "未找到 PayPal 注册邮箱输入框"
    if not set_locator_value(email_locator, email):
        return False, "填写 PayPal 注册邮箱失败"
    if on_progress:
        on_progress(progress_event("paypal_signup_email", url=getattr(api.page, "url", "")))
    before_url = str(getattr(api.page, "url", "") or "")
    submit_clicked = False
    if click_first(submit_selectors, 2500):
        submit_clicked = True
        if wait_step_advanced(api, before_url, timeout_seconds=6.0):
            return True, ""
        if logger:
            logger.info(
                "[paypal_signup] email submit clicked but page did not advance (SPA may be stuck), "
                "treating as submitted to allow stuck-recovery: before=%s current=%s",
                url_summary(before_url),
                url_summary(getattr(api.page, "url", "")),
            )
        return True, ""
    else:
        try:
            email_locator.press("Enter", timeout=1200)
            submit_clicked = True
        except Exception:
            pass
    if wait_step_advanced(api, before_url, timeout_seconds=4.0):
        return True, ""
    try:
        email_locator.press("Enter", timeout=1200)
        submit_clicked = True
    except Exception:
        pass
    if wait_step_advanced(api, before_url, timeout_seconds=4.0):
        return True, ""
    if js_click_submit(api):
        submit_clicked = True
        if wait_step_advanced(api, before_url, timeout_seconds=6.0):
            return True, ""
    if submit_clicked:
        if logger:
            logger.info(
                "[paypal_signup] email submit clicked but page did not advance (SPA may be stuck), "
                "treating as submitted to allow stuck-recovery: before=%s current=%s",
                url_summary(before_url),
                url_summary(getattr(api.page, "url", "")),
            )
        return True, ""
    if logger:
        logger.info(
            "[paypal_signup] email submit did not advance: before=%s current=%s gate=%s body=%s",
            url_summary(before_url),
            url_summary(getattr(api.page, "url", "")),
            compact_log_text(inspect_gate(api), limit=500),
            compact_log_text(body_excerpt(api, 500), limit=220),
        )
    return False, "PayPal 注册邮箱提交后未跳转到注册表单"


def click_paypal_phone_rejected_ok_in_frame(frame: Any) -> bool:
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


def dismiss_paypal_phone_rejected_prompt(
    api: Any,
    *,
    frames: Callable[[Any], list[Any]],
    click_ok_in_frame: Callable[[Any], bool],
    click_first: Callable[[list[str], int], bool],
    has_prompt: Callable[[Any], bool],
    prompt_selectors: list[str],
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    for frame in frames(api):
        if click_ok_in_frame(frame):
            sleep(1.0)
            if not has_prompt(api):
                return True
    for _ in range(3):
        if click_first(prompt_selectors, 1200):
            sleep(0.8)
            if not has_prompt(api):
                return True
        try:
            api.page.keyboard.press("Escape")
            sleep(0.5)
            if not has_prompt(api):
                return True
        except Exception:
            return False
    return not has_prompt(api)


def has_paypal_phone_rejected_prompt(
    api: Any,
    *,
    rejected_selectors: list[str],
    visible_locator: Callable[[list[str], int], Any],
    body_excerpt: BodyExcerpt,
    text_hint: Callable[[str], bool],
) -> bool:
    if visible_locator(rejected_selectors, 500):
        return True
    try:
        text = body_excerpt(api, 12000)
    except Exception:
        text = ""
    return text_hint(text)


def click_paypal_signup_otp_resend(
    api: Any,
    *,
    frames: Callable[[Any], list[Any]],
    click_first: Callable[[list[str], int], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    script = r"""
    () => {
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const textOf = (node) => String((node && (node.innerText || node.textContent || node.value)) || '').replace(/\s+/g, ' ').trim();
      const otpTextRe = /enter your code|6-digit code|verification code|security code|コードを入力|セキュリティコード|確認コード|認証コード|6桁のコード/i;
      const resendTextRe = /^resend$/i;
      const resendLooseRe = /resend|send again|send new code|コードを再送信|再送信|もう一度送信|再度送信|新しいコード/i;
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .modal, [class*="modal" i]'))
        .filter((node) => visible(node) && otpTextRe.test(textOf(node)));
      const roots = dialogs.length ? dialogs : [document.body];
      for (const root of roots) {
        const controls = Array.from(root.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
          .filter(visible);
        const resend = controls.find((node) => resendTextRe.test(textOf(node))) || controls.find((node) => resendLooseRe.test(textOf(node)));
        if (resend) {
          resend.click();
          return true;
        }
      }
      return false;
    }
    """
    for frame in frames(api):
        try:
            if frame.evaluate(script):
                if on_progress:
                    on_progress(progress_event("paypal_otp_resend_clicked", url=getattr(api.page, "url", "")))
                sleep(1.0)
                return True
        except Exception:
            continue
    if click_first(
        [
            'button:has-text("Resend")',
            'a:has-text("Resend")',
            '[role="button"]:has-text("Resend")',
            'button:has-text("再送信")',
            'a:has-text("再送信")',
            '[role="button"]:has-text("再送信")',
            'button:has-text("コードを再送信")',
            'a:has-text("コードを再送信")',
            'button:has-text("もう一度送信")',
            'a:has-text("もう一度送信")',
        ],
        1500,
    ):
        if on_progress:
            on_progress(progress_event("paypal_otp_resend_clicked", url=getattr(api.page, "url", "")))
        sleep(1.0)
        return True
    return False


def submit_paypal_login_step(
    api: Any,
    *,
    credentials: dict[str, str],
    state: dict[str, Any],
    next_selectors: list[str],
    set_locator_value: Callable[[Any, str], bool],
    click_first: Callable[[list[str], int], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
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
        if current.lower() != email.lower() and not set_locator_value(email_locator, email):
            return False, "填写 PayPal 邮箱失败"
        if on_progress:
            on_progress(progress_event("paypal_login_email", url=getattr(api.page, "url", "")))

    if phase in {"password", "login_combined"} and password_locator:
        if not password:
            return False, "自动 PayPal 模式缺少 paypal_password"
        if not set_locator_value(password_locator, password):
            return False, "填写 PayPal 密码失败"
        if on_progress:
            on_progress(progress_event("paypal_login_password", url=getattr(api.page, "url", "")))

    if not click_first(next_selectors, 2500):
        try:
            if password_locator:
                password_locator.press("Enter", timeout=1200)
            elif email_locator:
                email_locator.press("Enter", timeout=1200)
            else:
                return False, "未找到 PayPal 登录提交按钮"
        except Exception:
            return False, "未找到 PayPal 登录提交按钮"

    sleep(2.0)
    return True, ""


def click_paypal_approve(
    api: Any,
    *,
    approve_selectors: list[str],
    click_first: Callable[[list[str], int], bool],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    if not click_first(approve_selectors, 2500):
        return False
    if on_progress:
        on_progress(progress_event("paypal_approve_clicked", url=getattr(api.page, "url", "")))
    return True


def handle_paypal_left_host(
    *,
    current_url: str,
    otp_phone_lock_key: str,
    paypal_host: Callable[[str], bool],
    release_otp_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not current_url or paypal_host(current_url):
        return None
    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    if on_progress:
        on_progress(progress_event("paypal_wait_result", url=current_url))
    return {
        "action": "return_none",
        "otp_phone_lock_key": "",
    }


def paypal_left_host_values(left_host_result: dict[str, Any]) -> str:
    return str(left_host_result.get("otp_phone_lock_key") or "")


def prepare_paypal_authorize_flow_context(
    *,
    paypal_mode: str,
    credentials: dict[str, Any] | None,
    signup_profile: dict[str, Any] | None,
    phone_accounts: list[dict[str, Any]] | None,
    timeout_seconds: int,
    paypal_country: str,
    paypal_lang: str,
    normalize_paypal_country: Callable[[str], str],
    normalize_paypal_lang: Callable[..., str],
    signup_profiles_for_phone_pool: Callable[..., list[dict[str, Any]]],
    max_ddc_blocked_refreshes: int = 3,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    normalized_country = normalize_paypal_country(paypal_country)
    normalized_lang = normalize_paypal_lang(paypal_lang, normalized_country)
    signup_profiles = signup_profiles_for_phone_pool(signup_profile, phone_accounts)
    active_signup_profile = signup_profiles[0] if signup_profiles else (signup_profile or {})
    effective_credentials = dict(credentials or {})
    if paypal_mode == "create_account" and active_signup_profile:
        effective_credentials = {
            "email": str(active_signup_profile.get("email") or ""),
            "password": str(active_signup_profile.get("password") or ""),
        }
    return {
        "deadline": now() + max(20, timeout_seconds),
        "paypal_country": normalized_country,
        "paypal_lang": normalized_lang,
        "effective_credentials": effective_credentials,
        "signup_profiles": signup_profiles,
        "signup_profile_index": 0,
        "active_signup_profile": active_signup_profile,
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0.0,
        "signup_form_submitted": False,
        "signup_submitted_at": 0.0,
        "phone_only_retry": False,
        "card_retry_count": 0,
        "submitted_phone_keys": set(),
        "otp_phone_lock_key": "",
        "last_ddc_check_at": 0.0,
        "ddc_blocked_refresh_count": 0,
        "signup_login_redirect_count": 0,
        "state": {},
        "max_ddc_blocked_refreshes": max_ddc_blocked_refreshes,
    }


def handle_paypal_authorize_cancelled(
    *,
    is_cancelled,
    otp_phone_lock_key: str,
    release_otp_phone_lock: Callable[..., None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not (callable(is_cancelled) and is_cancelled()):
        return None
    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    return {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-cancelled",
        "failure_stage": "post_submit",
        "message": "任务已取消",
    }


def paypal_authorize_cancelled_result_fields(
    cancelled_result: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    return (
        str(cancelled_result.get("otp_phone_lock_key") or ""),
        str(cancelled_result.get("action") or "failed"),
        str(cancelled_result.get("screenshot_label") or "paypal-cancelled"),
        str(cancelled_result.get("failure_stage") or "post_submit"),
        str(cancelled_result.get("message") or "任务已取消"),
    )


def handle_paypal_phone_rejected_rotation(
    api: Any,
    *,
    paypal_mode: str,
    classified: dict[str, Any] | None,
    signup_profile_index: int,
    signup_profiles: list[dict[str, Any]],
    active_signup_profile: dict[str, Any],
    current_url: str,
    otp_phone_lock_key: str,
    dismiss_phone_rejected_prompt: Callable[[Any], bool],
    release_otp_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    url_summary: Callable[[str], str],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if (
        paypal_mode != "create_account"
        or not classified
        or classified.get("failure_stage") != "paypal_phone_rejected"
        or signup_profile_index + 1 >= len(signup_profiles)
    ):
        return None

    rejected_profile = active_signup_profile
    if on_progress:
        on_progress(
            progress_event(
                "paypal_phone_rejected_waiting_dismiss",
                phone_pool_index=signup_profile_index + 1,
                phone_pool_total=len(signup_profiles),
                rejected_phone=str(rejected_profile.get("phone") or ""),
                url=current_url,
                level="warn",
            )
        )
    if not dismiss_phone_rejected_prompt(api):
        sleep(1.0)
        return {"action": "continue"}

    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    next_signup_profile_index = signup_profile_index + 1
    next_signup_profile = signup_profiles[next_signup_profile_index]
    if on_progress:
        on_progress(
            progress_event(
                "paypal_phone_rejected_rotate",
                phone_pool_index=next_signup_profile_index + 1,
                phone_pool_total=len(signup_profiles),
                rejected_phone=str(rejected_profile.get("phone") or ""),
                next_phone=str(next_signup_profile.get("phone") or ""),
                sms_url=url_summary(str(next_signup_profile.get("sms_url") or "")),
                url=current_url,
                level="warn",
            )
        )
    sleep(1.5)
    return {
        "action": "continue",
        "otp_phone_lock_key": "",
        "signup_profile_index": next_signup_profile_index,
        "active_signup_profile": next_signup_profile,
        "signup_form_submitted": False,
        "signup_submitted_at": 0.0,
        "phone_only_retry": True,
        "card_retry_count": 0,
    }


def paypal_authorize_datadome_failed_result_fields(
    result: dict[str, Any],
    *,
    default_stage: str = "paypal_datadome_blocked",
    default_message: str,
) -> tuple[str, str, str]:
    return (
        str(result.get("otp_phone_lock_key") or ""),
        str(result.get("failure_stage") or default_stage),
        str(result.get("message") or default_message),
    )


def paypal_phone_rejected_rotation_values(
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
    return (
        str(rotation_result.get("otp_phone_lock_key", otp_phone_lock_key) or ""),
        int(rotation_result.get("signup_profile_index", signup_profile_index)),
        rotation_result.get("active_signup_profile", active_signup_profile),
        bool(rotation_result.get("signup_form_submitted", signup_form_submitted)),
        float(rotation_result.get("signup_submitted_at", signup_submitted_at) or 0),
        bool(rotation_result.get("phone_only_retry", phone_only_retry)),
        int(rotation_result.get("card_retry_count", card_retry_count)),
    )


def paypal_authorize_classified_return_values(
    classification_result: dict[str, Any],
    fallback_classified: dict[str, Any] | None,
    *,
    default_screenshot_label: str,
) -> tuple[str, str, dict[str, Any]]:
    return (
        str(classification_result.get("otp_phone_lock_key") or ""),
        str(classification_result.get("screenshot_label") or default_screenshot_label),
        classification_result.get("classified") or fallback_classified or {},
    )


def paypal_authorize_classification_refresh_count(
    classification_result: dict[str, Any],
    *,
    ddc_blocked_refresh_count: int,
) -> int:
    return int(classification_result.get("ddc_blocked_refresh_count", ddc_blocked_refresh_count))


def handle_paypal_authorize_failed_classification(
    api: Any,
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
    release_otp_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    logger: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if not classified or classified.get("status") != "failed":
        return None

    next_ddc_blocked_refresh_count = ddc_blocked_refresh_count
    if classified.get("failure_stage") == "paypal_datadome_blocked":
        next_ddc_blocked_refresh_count += 1
        if next_ddc_blocked_refresh_count <= max_ddc_blocked_refreshes:
            page = getattr(api, "page", None)
            if page:
                logger.info(
                    "[paypal_authorize] classify detected datadome_blocked, refreshing (%d/%d)...",
                    next_ddc_blocked_refresh_count,
                    max_ddc_blocked_refreshes,
                )
                if on_progress:
                    on_progress(
                        progress_event(
                            "paypal_ddc_blocked_retry",
                            f"classify 检测到 DataDome 封锁，正在刷新重试 ({next_ddc_blocked_refresh_count}/{max_ddc_blocked_refreshes})",
                        )
                    )
                try:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                sleep(4)
                return {
                    "action": "continue",
                    "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
                }

    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    if paypal_mode == "create_account" and classified.get("failure_stage") == "paypal_phone_rejected" and on_progress:
        on_progress(
            progress_event(
                "paypal_phone_rejected_final",
                rejected_phone=str(active_signup_profile.get("phone") or ""),
                phone_pool_index=signup_profile_index + 1,
                phone_pool_total=len(signup_profiles),
                url=current_url,
                level="warn",
            )
        )
    return {
        "action": "return_classified",
        "classified": classified,
        "otp_phone_lock_key": "",
        "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
        "screenshot_label": "paypal-authorize-failed",
    }


def handle_paypal_authorize_review_classification(
    api: Any,
    *,
    classified: dict[str, Any] | None,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
    max_ddc_blocked_refreshes: int,
    is_ddc_blocked_page: Callable[[Any], bool],
    release_otp_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    logger: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if (
        not classified
        or classified.get("status") != "needs_review"
        or classified.get("failure_stage") != "paypal_human_verification"
    ):
        return None

    next_ddc_blocked_refresh_count = ddc_blocked_refresh_count
    page = getattr(api, "page", None)
    if page and is_ddc_blocked_page(page):
        next_ddc_blocked_refresh_count += 1
        if next_ddc_blocked_refresh_count <= max_ddc_blocked_refreshes:
            logger.info(
                "[paypal_authorize] human_verification is actually a blocked page, refreshing (%d/%d)...",
                next_ddc_blocked_refresh_count,
                max_ddc_blocked_refreshes,
            )
            if on_progress:
                on_progress(
                    progress_event(
                        "paypal_ddc_blocked_retry",
                        f"DataDome 封锁页面被误判为人机验证，正在刷新重试 ({next_ddc_blocked_refresh_count}/{max_ddc_blocked_refreshes})",
                    )
                )
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            sleep(4)
            return {
                "action": "continue",
                "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
            }

    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    return {
        "action": "return_classified",
        "classified": classified,
        "otp_phone_lock_key": "",
        "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
        "screenshot_label": "paypal-authorize-review",
    }


def handle_paypal_authorize_ddc_blocked_page(
    api: Any,
    *,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
    max_ddc_blocked_refreshes: int,
    is_ddc_blocked_page: Callable[[Any], bool],
    release_otp_phone_lock: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    logger: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    page = getattr(api, "page", None)
    if not (page and is_ddc_blocked_page(page)):
        return None

    next_ddc_blocked_refresh_count = ddc_blocked_refresh_count + 1
    if next_ddc_blocked_refresh_count > max_ddc_blocked_refreshes:
        if otp_phone_lock_key:
            release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
        return {
            "action": "failed",
            "otp_phone_lock_key": "",
            "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
            "failure_stage": "paypal_datadome_blocked",
            "message": f"DataDome 封锁页面刷新 {max_ddc_blocked_refreshes} 次仍未恢复",
        }

    logger.info(
        "[paypal_authorize] blocked page detected in main loop, refreshing (%d/%d)...",
        next_ddc_blocked_refresh_count,
        max_ddc_blocked_refreshes,
    )
    if on_progress:
        on_progress(
            progress_event(
                "paypal_ddc_blocked_retry",
                f"检测到 DataDome 封锁页面，正在刷新重试 ({next_ddc_blocked_refresh_count}/{max_ddc_blocked_refreshes})",
            )
        )
    try:
        page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    sleep(4)
    return {
        "action": "continue",
        "otp_phone_lock_key": otp_phone_lock_key,
        "ddc_blocked_refresh_count": next_ddc_blocked_refresh_count,
    }


def paypal_authorize_ddc_blocked_page_values(
    blocked_page_result: dict[str, Any],
    *,
    otp_phone_lock_key: str,
    ddc_blocked_refresh_count: int,
) -> tuple[str, int]:
    return (
        str(blocked_page_result.get("otp_phone_lock_key", otp_phone_lock_key) or ""),
        int(blocked_page_result.get("ddc_blocked_refresh_count", ddc_blocked_refresh_count)),
    )


def handle_paypal_authorize_ddc_challenge(
    api: Any,
    *,
    otp_phone_lock_key: str,
    last_ddc_check_at: float,
    ddc_iframe_check_interval: float,
    ddc_pass_timeout_seconds: int,
    ddc_slider_visible: Callable[[Any], bool],
    has_ddc_iframe: Callable[[Any], bool],
    wait_ddc_pass: Callable[..., bool],
    release_otp_phone_lock: Callable[..., None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    now: Callable[[], float] = time.time,
) -> dict[str, Any] | None:
    page = getattr(api, "page", None)
    if not page:
        return None

    slider_visible = ddc_slider_visible(page)
    ddc_iframe_present = False
    if not slider_visible and now() - last_ddc_check_at > ddc_iframe_check_interval:
        ddc_iframe_present = has_ddc_iframe(page)
    if not (slider_visible or ddc_iframe_present):
        return None

    next_last_ddc_check_at = now()
    if wait_ddc_pass(page, timeout_seconds=ddc_pass_timeout_seconds, on_progress=on_progress):
        return {
            "action": "passed",
            "otp_phone_lock_key": otp_phone_lock_key,
            "last_ddc_check_at": next_last_ddc_check_at,
        }

    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    return {
        "action": "failed",
        "otp_phone_lock_key": "",
        "last_ddc_check_at": next_last_ddc_check_at,
        "failure_stage": "paypal_datadome_blocked",
        "message": "DataDome 滑块/风控验证未通过",
    }


def paypal_authorize_ddc_challenge_values(
    ddc_challenge_result: dict[str, Any],
    *,
    otp_phone_lock_key: str,
    last_ddc_check_at: float,
) -> tuple[str, float]:
    return (
        str(ddc_challenge_result.get("otp_phone_lock_key", otp_phone_lock_key) or ""),
        float(ddc_challenge_result.get("last_ddc_check_at", last_ddc_check_at) or 0),
    )


def handle_paypal_result_datadome_check(
    api: Any,
    *,
    last_ddc_check_at: float,
    ddc_iframe_check_interval: float,
    ddc_pass_timeout_seconds: int,
    is_ddc_blocked_page: Callable[[Any], bool],
    ddc_slider_visible: Callable[[Any], bool],
    has_ddc_iframe: Callable[[Any], bool],
    wait_ddc_pass: Callable[..., bool],
    logger: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    page = getattr(api, "page", None)
    if not page:
        return None

    if is_ddc_blocked_page(page):
        logger.info("[paypal_result] blocked page detected, refreshing...")
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        sleep(4)
        return {
            "action": "continue",
            "last_ddc_check_at": last_ddc_check_at,
        }

    slider_visible = ddc_slider_visible(page)
    ddc_iframe_present = False
    if not slider_visible and now() - last_ddc_check_at > ddc_iframe_check_interval:
        ddc_iframe_present = has_ddc_iframe(page)
    if not (slider_visible or ddc_iframe_present):
        return None

    next_last_ddc_check_at = now()
    wait_ddc_pass(page, timeout_seconds=ddc_pass_timeout_seconds, on_progress=on_progress)
    return {
        "action": "checked",
        "last_ddc_check_at": next_last_ddc_check_at,
    }


def paypal_result_datadome_values(
    datadome_result: dict[str, Any],
    *,
    last_ddc_check_at: float,
) -> float:
    return float(datadome_result.get("last_ddc_check_at", last_ddc_check_at) or 0)


def should_continue_after_paypal_result_datadome(datadome_result: dict[str, Any]) -> bool:
    return datadome_result.get("action") == "continue"


def paypal_result_datadome_transition(
    datadome_result: dict[str, Any],
    *,
    last_ddc_check_at: float,
) -> tuple[float, bool]:
    return (
        paypal_result_datadome_values(datadome_result, last_ddc_check_at=last_ddc_check_at),
        should_continue_after_paypal_result_datadome(datadome_result),
    )


def should_check_paypal_result_datadome(
    current_url: str,
    *,
    is_paypal_host: Callable[[str], bool],
) -> bool:
    return is_paypal_host(current_url)


def paypal_result_browser_classification(
    current_url: str,
    body_text: str,
    *,
    classify_checkout_state: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    return classify_checkout_state(current_url, body_text)


def paypal_result_browser_classified_values(
    current_url: str,
    body_text: str,
    *,
    classify_checkout_state: Callable[[str, str], dict[str, Any] | None],
) -> tuple[str, dict[str, Any]] | None:
    classified_result = paypal_result_browser_classification(
        current_url,
        body_text,
        classify_checkout_state=classify_checkout_state,
    )
    if not classified_result:
        return None
    return paypal_result_classified_return_values(classified_result)


def paypal_result_classified_return_values(classified_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        str(classified_result["status"]),
        classified_result,
    )


def attach_paypal_result_screenshot_paths(
    classified_result: dict[str, Any],
    screenshot_paths: list[str],
) -> dict[str, Any]:
    classified_result["screenshot_paths"] = screenshot_paths
    return classified_result


def paypal_result_cancelled_result_fields(result: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    result = result or {}
    return (
        str(result.get("action") or "failed"),
        str(result.get("screenshot_label") or "paypal-cancelled"),
        str(result.get("failure_stage") or "post_submit"),
        str(result.get("message") or "任务已取消"),
    )


def paypal_result_timeout_result_fields(result: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
    result = result or {}
    return (
        str(result.get("action") or "needs_review"),
        str(result.get("screenshot_label") or "paypal-timeout"),
        str(result.get("failure_stage") or "post_submit"),
        str(result.get("message") or "等待 PayPal 支付结果超时，需要人工确认最终状态"),
    )


def paypal_result_wait_deadline(*, now: float, timeout_seconds: int) -> float:
    return now + max(10, timeout_seconds)


def should_continue_paypal_result_wait(*, now: float, deadline: float) -> bool:
    return now < deadline


def should_cancel_paypal_result_wait(is_cancelled: Callable[[], bool] | None) -> bool:
    return callable(is_cancelled) and is_cancelled()


def paypal_result_wait_initial_state() -> tuple[str, float, float, float]:
    return "", 0.0, 0.0, 0.0


def paypal_result_wait_sleep_seconds() -> float:
    return 3.0


def paypal_result_autofilled_url_keys() -> set[str]:
    return set()


def paypal_result_stripe_state_http_session(
    proxy_url: str | None,
    *,
    new_http_session: Callable[..., Any],
) -> Any:
    return new_http_session(proxy_url, require_curl_cffi=False)


def paypal_result_page_snapshot(
    api: Any,
    *,
    body_excerpt: Callable[[Any], str],
) -> tuple[str, str]:
    return body_excerpt(api), getattr(api.page, "url", "")


def paypal_result_sync_prefer_paypal() -> bool:
    return True


def paypal_result_autofill_url_key(url: str) -> str:
    parts = urlsplit(str(url or ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def should_autofill_paypal_result_checkout(
    current_url: str,
    autofill_payload: dict[str, Any] | None,
    *,
    autofill_enabled: bool = True,
    is_checkout_host: Callable[[str], bool],
    autofill_allowed: Callable[[str], bool],
) -> bool:
    return (
        autofill_enabled and bool(autofill_payload) and is_checkout_host(current_url) and autofill_allowed(current_url)
    )


def should_run_paypal_result_autofill(
    *,
    should_autofill_checkout: bool,
    autofill_key: str,
    autofilled_url_keys: set[str],
) -> bool:
    return should_autofill_checkout and autofill_key not in autofilled_url_keys


def paypal_result_autofill_transition(
    current_url: str,
    autofill_payload: dict[str, Any] | None,
    *,
    autofilled_url_keys: set[str],
    autofill_enabled: bool = True,
    is_checkout_host: Callable[[str], bool],
    autofill_allowed: Callable[[str], bool],
) -> tuple[bool, str]:
    should_autofill_checkout = should_autofill_paypal_result_checkout(
        current_url,
        autofill_payload,
        autofill_enabled=autofill_enabled,
        is_checkout_host=is_checkout_host,
        autofill_allowed=autofill_allowed,
    )
    autofill_key = paypal_result_autofill_url_key(current_url)
    return (
        should_run_paypal_result_autofill(
            should_autofill_checkout=should_autofill_checkout,
            autofill_key=autofill_key,
            autofilled_url_keys=autofilled_url_keys,
        ),
        autofill_key,
    )


def record_paypal_result_autofill_key(
    autofilled_url_keys: set[str],
    autofill_key: str,
) -> set[str]:
    autofilled_url_keys.add(autofill_key)
    return autofilled_url_keys


def paypal_result_stripe_progress_event_fields(
    stripe_classified: dict[str, Any],
    *,
    checkout_url: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any]]:
    return (
        "paypal_result_confirmed_by_stripe",
        str(stripe_classified.get("message") or "Stripe checkout 状态已确认"),
        {
            "checkout_url": checkout_url,
            "url": current_url,
        },
    )


def paypal_result_stripe_classified_values(
    stripe_classified: dict[str, Any],
    *,
    checkout_url: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any], str, dict[str, Any]]:
    progress_stage, progress_message, progress_extra = paypal_result_stripe_progress_event_fields(
        stripe_classified,
        checkout_url=checkout_url,
        current_url=current_url,
    )
    screenshot_label, classified_result = paypal_result_classified_return_values(stripe_classified)
    return progress_stage, progress_message, progress_extra, screenshot_label, classified_result


def should_poll_paypal_result_stripe_state(
    *,
    checkout_url: str,
    now: float,
    last_poll_at: float,
    poll_interval_seconds: float,
) -> bool:
    return bool(checkout_url) and now - last_poll_at >= poll_interval_seconds


def paypal_result_stripe_poll_transition(
    *,
    checkout_url: str,
    now: float,
    last_poll_at: float,
    poll_interval_seconds: float,
) -> tuple[bool, float]:
    should_poll = should_poll_paypal_result_stripe_state(
        checkout_url=checkout_url,
        now=now,
        last_poll_at=last_poll_at,
        poll_interval_seconds=poll_interval_seconds,
    )
    return should_poll, now if should_poll else last_poll_at


def should_emit_paypal_result_stage_progress(*, stage: str, last_stage: str) -> bool:
    return stage != last_stage


def paypal_result_stage_values(
    current_url: str,
    body_text: str,
    *,
    infer_stage: Callable[[str, str], tuple[str, str]],
) -> tuple[str, str]:
    return infer_stage(current_url, body_text)


def paypal_result_stage_progress_transition(*, stage: str, last_stage: str) -> tuple[bool, str]:
    should_emit = should_emit_paypal_result_stage_progress(stage=stage, last_stage=last_stage)
    return should_emit, stage if should_emit else last_stage


def paypal_result_stage_progress_event_fields(
    *,
    stage: str,
    message: str,
    current_url: str,
) -> tuple[str, str, dict[str, Any]]:
    return (
        stage,
        message,
        {"url": current_url},
    )


def should_log_paypal_result_wait(
    *,
    now: float,
    last_log_at: float,
    log_interval_seconds: float,
) -> bool:
    return now - last_log_at >= log_interval_seconds


def paypal_result_wait_log_transition(
    *,
    now: float,
    last_log_at: float,
    log_interval_seconds: float,
) -> tuple[bool, float]:
    should_log = should_log_paypal_result_wait(
        now=now,
        last_log_at=last_log_at,
        log_interval_seconds=log_interval_seconds,
    )
    return should_log, now if should_log else last_log_at


def paypal_result_wait_log_values(
    *,
    deadline: float,
    now: float,
    current_url: str,
) -> tuple[int, str]:
    return (
        max(0, int(deadline - now)),
        current_url,
    )


def handle_paypal_browser_fallback_ddc_wait(
    page: Any,
    *,
    wait_ddc_pass: Callable[..., bool],
    timeout_seconds: int,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if wait_ddc_pass(page, timeout_seconds=timeout_seconds, on_progress=on_progress):
        return {"action": "continue"}
    return {
        "action": "failed",
        "failure_stage": "paypal_datadome_blocked",
        "message": "浏览器降级后 DataDome 滑块/风控仍未通过",
    }


def handle_paypal_protocol_browser_fallback_context(
    protocol_result: dict[str, Any],
    *,
    paypal_mode: str,
    paypal_country: str,
    paypal_lang: str,
    extract_ba_token: Callable[[str], str],
    create_account_entry_url: Callable[..., str],
    safe_url_summary: Callable[[str], str],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    fallback_approve_url = str(protocol_result.get("paypal_approve_url") or "")
    fallback_ba_token = str(protocol_result.get("ba_token") or extract_ba_token(fallback_approve_url) or "")
    if on_progress:
        on_progress(
            progress_event(
                "paypal_protocol_browser_fallback",
                "协议模式被 PayPal 风控拦截，正在降级到浏览器模式",
                paypal_approve_url=safe_url_summary(fallback_approve_url),
                ba_token=fallback_ba_token,
            )
        )
    if not fallback_approve_url:
        return {
            "action": "return_protocol_result",
            "protocol_result": protocol_result,
            "paypal_approve_url": fallback_approve_url,
            "ba_token": fallback_ba_token,
        }

    browser_entry_url = fallback_approve_url
    if paypal_mode == "create_account":
        browser_entry_url = (
            create_account_entry_url(
                fallback_approve_url,
                ba_token=fallback_ba_token,
                country=paypal_country,
                lang=paypal_lang,
            )
            or fallback_approve_url
        )
    return {
        "action": "fallback",
        "paypal_approve_url": fallback_approve_url,
        "ba_token": fallback_ba_token,
        "browser_entry_url": browser_entry_url,
    }


def preserve_paypal_roxybrowser_on_failure(
    api: Any,
    result: dict[str, Any],
    *,
    fallback_use_roxybrowser: bool,
    keepalive_seconds: int,
) -> dict[str, Any]:
    if fallback_use_roxybrowser and str(result.get("status") or "") != "success":
        api._preserve_roxybrowser_on_stop = True
        api._preserve_roxybrowser_on_stop_seconds = keepalive_seconds
    return result


def handle_paypal_pre_extracted_checkout_without_ba(
    pre_extracted: dict[str, Any] | None,
    *,
    safe_url_summary: Callable[[str], str],
    progress_event: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    pre_extracted_checkout_url = str((pre_extracted or {}).get("checkout_url") or "").strip()
    pre_extracted_ba_token = str((pre_extracted or {}).get("ba_token") or "").strip()
    if not (pre_extracted_checkout_url and not pre_extracted_ba_token):
        return None

    if on_progress:
        on_progress(
            progress_event(
                "paypal_protocol_checkout_without_ba",
                "协议模式已获取长 checkout 链接但未拿到 BA 链接，已停止浏览器回退",
                checkout_url=safe_url_summary(pre_extracted_checkout_url),
                reason=str((pre_extracted or {}).get("failure_stage") or ""),
                level="warn",
            )
        )
    return {
        "action": "failed",
        "failure_stage": str((pre_extracted or {}).get("failure_stage") or "extract_ba_link_poll"),
        "message": str(
            (pre_extracted or {}).get("message") or "协议模式已获取长 checkout 链接但未拿到 PayPal BA/授权链接"
        ),
        "checkout_url": pre_extracted_checkout_url,
    }


def handle_paypal_proxy_open_checkout_failure(
    prepare_result: dict[str, Any] | None,
    *,
    proxy_url: str | None,
    is_tunnel_connection_error: Callable[[Any], bool],
    safe_url_summary: Callable[[str], str],
    progress_event: Callable[..., dict[str, Any]],
    logger: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not (prepare_result and prepare_result.get("failure_stage") == "open_checkout" and proxy_url):
        return None

    retry_message = "代理打开 checkout 失败，已停止当前账号；不会切换直连重试"
    if is_tunnel_connection_error(prepare_result.get("message")):
        retry_message = "代理隧道打开 checkout 失败，已停止当前账号；不会切换直连重试"
    if on_progress:
        on_progress(
            progress_event(
                "paypal_proxy_open_checkout_failed",
                retry_message,
                level="warn",
            )
        )
    logger.info(
        "[paypal_bind_executor] checkout open failed with proxy, not retrying direct: proxy=%s",
        safe_url_summary(proxy_url),
    )
    return {
        "action": "failed",
        "failure_stage": "open_checkout_proxy",
        "message": f"{retry_message}: {prepare_result.get('message') or '未知错误'}",
    }


def handle_paypal_manual_pre_wait_autofill(
    api: Any,
    *,
    autofill_payload: dict[str, Any] | None,
    autofill_enabled: bool = True,
    autofill_checkout_fields: Callable[..., None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not autofill_enabled or not autofill_payload:
        return None
    autofill_checkout_fields(api, autofill_payload, on_progress=on_progress)
    return {"action": "autofilled"}


def handle_paypal_open_checkout_cancelled(*, is_cancelled) -> dict[str, Any] | None:
    if not (callable(is_cancelled) and is_cancelled()):
        return None
    return {
        "action": "failed",
        "failure_stage": "open_checkout",
        "message": "任务已取消",
    }


def launch_paypal_checkout_browser(
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
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    launch_browser: Callable[..., Any],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    browser_locale = f"{paypal_lang}-{paypal_country}"
    browser_accept_language = f"{paypal_lang}-{paypal_country},{paypal_lang};q=0.9,en;q=0.8"
    launch_browser(
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        background=False,
        locale=browser_locale,
        accept_language=browser_accept_language,
        randomize_fingerprint=False,
        use_camoufox=fallback_use_camoufox if use_fallback_browser else use_camoufox,
        use_roxybrowser=fallback_use_roxybrowser if use_fallback_browser else use_roxybrowser,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        on_progress=on_progress,
    )


def handle_paypal_checkout_context_dispatch(
    api: Any,
    *,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    session_id: str,
    screenshot_paths: list[str],
    is_cancelled,
    handle_open_checkout_cancelled: Callable[..., dict[str, Any] | None],
    build_result: Callable[..., dict[str, Any]],
    prepare_chatgpt_checkout_context: Callable[..., dict[str, Any] | None],
    extract_auth_session_context: Callable[[str], dict[str, Any]],
    handle_proxy_open_checkout_failure: Callable[..., dict[str, Any] | None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    open_checkout_cancelled = handle_open_checkout_cancelled(is_cancelled=is_cancelled)
    if open_checkout_cancelled:
        return build_result(
            str(open_checkout_cancelled.get("action") or "failed"),
            failure_stage=str(open_checkout_cancelled.get("failure_stage") or "open_checkout"),
            message=str(open_checkout_cancelled.get("message") or "任务已取消"),
        )

    normalized_email = str(email or "").strip()
    prepare_result = prepare_chatgpt_checkout_context(
        api,
        email=normalized_email,
        checkout_url=checkout_url,
        session_context=extract_auth_session_context(normalized_email) if email else {},
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        on_progress=on_progress,
    )
    proxy_open_failure = handle_proxy_open_checkout_failure(
        prepare_result,
        proxy_url=proxy_url,
        on_progress=on_progress,
    )
    if proxy_open_failure:
        return build_result(
            str(proxy_open_failure.get("action") or "failed"),
            failure_stage=str(proxy_open_failure.get("failure_stage") or "open_checkout_proxy"),
            message=str(
                proxy_open_failure.get("message")
                or "代理打开 checkout 失败，已停止当前账号；不会切换直连重试: 未知错误"
            ),
            screenshot_paths=screenshot_paths,
        )
    if prepare_result:
        return prepare_result
    return None


def handle_paypal_manual_result_wait(
    api: Any,
    *,
    checkout_url: str,
    proxy_url: str | None,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    manual_pre_wait_autofill: Callable[..., dict[str, Any] | None],
    wait_for_paypal_result: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    manual_pre_wait_autofill(
        api,
        autofill_payload=autofill_payload,
        autofill_enabled=autofill_enabled,
        on_progress=on_progress,
    )
    return wait_for_paypal_result(
        api,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
    )


def handle_paypal_post_checkout_flow_dispatch(
    api: Any,
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
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    handle_auto_flow_dispatch: Callable[..., dict[str, Any] | None],
    handle_manual_result_wait: Callable[..., dict[str, Any]],
    paypal_result_timeout_seconds: Callable[[int], int],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    auto_flow_result = handle_auto_flow_dispatch(
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
        on_progress=on_progress,
    )
    if auto_flow_result is not None:
        return auto_flow_result

    return handle_manual_result_wait(
        api,
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=paypal_result_timeout_seconds(timeout_seconds),
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        autofill_enabled=autofill_enabled,
        autofill_payload=autofill_payload,
    )


def handle_paypal_unexpected_error(
    api: Any,
    exc: Exception,
    *,
    session_id: str,
    screenshot_paths: list[str],
    logger: Any,
    capture_screenshot: Callable[..., Any],
    build_result: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    logger.exception("[paypal_bind_executor] unexpected error")
    capture_screenshot(api, session_id, "paypal-unexpected-error", screenshot_paths)
    return build_result(
        "failed",
        failure_stage="post_submit",
        message=f"执行 PayPal 任务时出现异常: {exc}",
        screenshot_paths=screenshot_paths,
    )


def stop_paypal_api_safely(api: Any) -> None:
    try:
        api.stop()
    except Exception:
        pass


def prepare_paypal_auto_flow_payloads(
    *,
    autofill_payload: dict[str, Any] | None,
    autofill_enabled: bool,
    paypal_country: str,
    proxy_url: str | None,
    resolve_checkout_billing_payload: Callable[..., dict[str, Any]],
    prepare_signup_billing_payload: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    billing_payload = resolve_checkout_billing_payload(autofill_payload, auto_generate=bool(autofill_enabled))
    signup_billing_payload = prepare_signup_billing_payload(
        billing_payload,
        paypal_country=paypal_country,
        proxy_url=proxy_url,
        auto_generate=bool(autofill_enabled),
    )
    return {
        "billing_payload": billing_payload,
        "signup_billing_payload": signup_billing_payload,
    }


def prepare_paypal_auto_flow_identity(
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
    normalize_paypal_credentials: Callable[..., dict[str, Any]],
    build_paypal_signup_profile: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return {
        "paypal_credentials": normalize_paypal_credentials(paypal_email, paypal_password),
        "signup_profile": build_paypal_signup_profile(
            paypal_email=paypal_email,
            paypal_password=paypal_password,
            billing_payload=signup_billing_payload,
            paypal_country=paypal_country,
            sms_url=sms_url,
            otp_channel=otp_channel,
            paypal_card_number=paypal_card_number,
            paypal_card_expiry=paypal_card_expiry,
            paypal_card_cvv=paypal_card_cvv,
        ),
    }


def handle_paypal_auto_flow_dispatch(
    api: Any,
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
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    prepare_auto_flow_payloads: Callable[..., dict[str, Any]],
    prepare_auto_flow_identity: Callable[..., dict[str, Any]],
    run_paypal_auto_flow: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not auto_mode:
        return None

    auto_flow_payloads = prepare_auto_flow_payloads(
        autofill_payload=autofill_payload,
        autofill_enabled=autofill_enabled,
        paypal_country=paypal_country,
        proxy_url=proxy_url,
    )
    billing_payload = auto_flow_payloads["billing_payload"]
    signup_billing_payload = auto_flow_payloads["signup_billing_payload"]
    auto_flow_identity = prepare_auto_flow_identity(
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        signup_billing_payload=signup_billing_payload,
        paypal_country=paypal_country,
        sms_url=sms_url,
        otp_channel=otp_channel,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
    )
    return run_paypal_auto_flow(
        api,
        email=str(email or "").strip(),
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_credentials=auto_flow_identity["paypal_credentials"],
        signup_profile=auto_flow_identity["signup_profile"],
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


def handle_paypal_auto_flow_checkout_handoff(
    api: Any,
    *,
    current_url: str,
    email: str,
    billing_payload: dict[str, Any],
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled,
    progress: Callable[..., Any],
    is_checkout_host: Callable[[str], bool],
    page_url: Callable[[], str],
    browser_checkout_nonzero_amount_hint: Callable[[Any], str],
    capture_screenshot: Callable[..., Any],
    build_result: Callable[..., dict[str, Any]],
    select_paypal_option: Callable[..., bool],
    autofill_allowed: Callable[[str], bool],
    has_complete_billing_payload: Callable[[dict[str, Any]], bool],
    emit_progress: Callable[..., None],
    progress_event: Callable[..., dict[str, Any]],
    fill_paypal_checkout_billing_form: Callable[..., tuple[bool, str]],
    accept_checkout_terms_on_page: Callable[..., Any],
    submit_checkout_to_paypal: Callable[..., dict[str, Any] | None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not is_checkout_host(current_url):
        return None

    nonzero_hint = browser_checkout_nonzero_amount_hint(api)
    if nonzero_hint:
        capture_screenshot(api, session_id, "paypal-browser-nonzero-amount-blocked", screenshot_paths)
        return build_result(
            "failed",
            failure_stage="browser_charge_guard",
            message=f"浏览器 checkout 页面今日应付金额非 0 ({nonzero_hint})，已跳过当前账号",
            screenshot_paths=screenshot_paths,
        )

    if not select_paypal_option(api, on_progress=on_progress):
        capture_screenshot(api, session_id, "paypal-option-not-found", screenshot_paths)
        return build_result(
            "failed",
            failure_stage="select_paypal",
            message="未找到 PayPal 支付方式按钮",
            screenshot_paths=screenshot_paths,
        )

    if autofill_allowed(page_url()):
        if not has_complete_billing_payload(billing_payload):
            capture_screenshot(api, session_id, "paypal-billing-address-incomplete", screenshot_paths)
            return build_result(
                "failed",
                failure_stage="fill_billing_info",
                message="账单地址缺少必要字段",
                screenshot_paths=screenshot_paths,
            )
        emit_progress(
            on_progress,
            progress_event(
                "paypal_billing_fill_started",
                url=page_url(),
                billing_info=billing_payload,
            ),
        )
        ok, error = fill_paypal_checkout_billing_form(
            api,
            billing_payload,
            session_id,
            screenshot_paths,
            on_progress=on_progress,
        )
        if not ok:
            return build_result(
                "failed",
                failure_stage="fill_billing_info",
                message=f"自动填写 checkout 账单地址失败: {error}",
                screenshot_paths=screenshot_paths,
            )
        accept_checkout_terms_on_page(api, progress=progress)
        emit_progress(
            on_progress,
            progress_event("paypal_billing_fill_done", url=page_url()),
        )
    else:
        accept_checkout_terms_on_page(api, progress=progress)

    handoff_result = submit_checkout_to_paypal(
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
    return None


def run_paypal_auto_flow_sequence(
    api: Any,
    *,
    email: str,
    checkout_url: str,
    proxy_url: str | None,
    paypal_mode: str,
    paypal_credentials: dict[str, Any],
    signup_profile: dict[str, Any] | None,
    phone_accounts: list[dict[str, Any]] | None,
    billing_payload: dict[str, Any] | None,
    paypal_country: str,
    paypal_lang: str,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    page_url: Callable[[], str],
    resolve_checkout_billing_payload: Callable[..., dict[str, Any]],
    normalize_paypal_country: Callable[[str], str],
    normalize_paypal_lang: Callable[..., str],
    progress_adapter: Callable[..., Callable[..., Any]],
    handle_checkout_handoff: Callable[..., dict[str, Any] | None],
    run_paypal_authorize_flow: Callable[..., dict[str, Any] | None],
    paypal_authorize_timeout_seconds: Callable[[int], int],
    wait_for_paypal_result: Callable[..., dict[str, Any]],
    paypal_result_timeout_seconds: Callable[[int], int],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    current_url = page_url()
    billing_payload = dict(
        billing_payload or resolve_checkout_billing_payload(autofill_payload, auto_generate=bool(autofill_enabled))
    )
    paypal_country = normalize_paypal_country(paypal_country or str(billing_payload.get("country") or "US"))
    paypal_lang = normalize_paypal_lang(paypal_lang, paypal_country)
    progress = progress_adapter(on_progress)
    authorize_timeout_seconds = paypal_authorize_timeout_seconds(timeout_seconds)
    result_timeout_seconds = paypal_result_timeout_seconds(timeout_seconds)

    handoff_result = handle_checkout_handoff(
        api,
        current_url=current_url,
        email=email,
        billing_payload=billing_payload,
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        progress=progress,
        on_progress=on_progress,
    )
    if handoff_result:
        return handoff_result

    authorize_result = run_paypal_authorize_flow(
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

    return wait_for_paypal_result(
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


def handle_paypal_protocol_flow_dispatch(
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
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    pre_extracted: dict[str, Any] | None,
    prepare_auto_flow_payloads: Callable[..., dict[str, Any]],
    build_paypal_signup_profile: Callable[..., dict[str, Any]],
    run_paypal_protocol_flow: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    auto_flow_payloads = prepare_auto_flow_payloads(
        autofill_payload=autofill_payload,
        autofill_enabled=autofill_enabled,
        paypal_country=paypal_country,
        proxy_url=proxy_url,
    )
    billing_payload = auto_flow_payloads["billing_payload"]
    signup_billing_payload = auto_flow_payloads["signup_billing_payload"]
    signup_profile = build_paypal_signup_profile(
        paypal_email=paypal_email,
        paypal_password=paypal_password,
        billing_payload=signup_billing_payload,
        paypal_country=paypal_country,
        sms_url=sms_url,
        otp_channel=otp_channel,
        phone_accounts=phone_accounts,
        paypal_card_number=paypal_card_number,
        paypal_card_expiry=paypal_card_expiry,
        paypal_card_cvv=paypal_card_cvv,
    )
    protocol_result = run_paypal_protocol_flow(
        email=str(email or "").strip(),
        checkout_url=checkout_url,
        proxy_url=proxy_url,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        billing_payload=billing_payload,
        timeout_seconds=timeout_seconds,
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        pre_extracted=pre_extracted,
    )
    return {
        "billing_payload": billing_payload,
        "signup_billing_payload": signup_billing_payload,
        "protocol_result": protocol_result,
    }


def handle_paypal_protocol_browser_fallback_dispatch(
    api: Any,
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
    is_cancelled,
    launch_browser: Callable[..., Any],
    emit_progress: Callable[..., Any],
    progress_event: Callable[..., dict[str, Any]],
    goto_paypal_page_with_retries: Callable[..., Any],
    handle_browser_fallback_ddc_wait: Callable[..., dict[str, Any]],
    build_result: Callable[..., dict[str, Any]],
    preserve_roxybrowser_on_failure: Callable[[dict[str, Any]], dict[str, Any]],
    ensure_captcha_bypass: Callable[..., Any],
    normalize_paypal_credentials: Callable[..., dict[str, Any]],
    build_paypal_signup_profile: Callable[..., dict[str, Any]],
    run_paypal_authorize_flow: Callable[..., dict[str, Any] | None],
    paypal_authorize_timeout_seconds: Callable[[int], int],
    wait_for_paypal_result: Callable[..., dict[str, Any]],
    paypal_result_timeout_seconds: Callable[[int], int],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    launch_browser(
        proxy_url=proxy_url,
        proxy_bypass=proxy_bypass,
        background=False,
        locale=f"{paypal_lang}-{paypal_country}",
        accept_language=f"{paypal_lang}-{paypal_country},{paypal_lang};q=0.9,en;q=0.8",
        use_camoufox=fallback_use_camoufox,
        use_roxybrowser=fallback_use_roxybrowser,
        roxybrowser_workspace_id=roxybrowser_workspace_id,
        roxybrowser_profile_id=roxybrowser_profile_id,
        on_progress=on_progress,
    )
    page = getattr(api, "page", None)
    emit_progress(on_progress, progress_event("paypal_browser_fallback_navigate"))
    browser_entry_url = str(fallback_context.get("browser_entry_url") or fallback_approve_url)
    goto_paypal_page_with_retries(
        page,
        browser_entry_url,
        on_progress=on_progress,
        attempts=3,
        timeout_ms=60000,
    )
    emit_progress(on_progress, progress_event("paypal_browser_fallback_ddc_wait"))
    fallback_ddc_result = handle_browser_fallback_ddc_wait(page, on_progress=on_progress)
    if fallback_ddc_result.get("action") == "failed":
        return preserve_roxybrowser_on_failure(
            build_result(
                "failed",
                failure_stage=str(fallback_ddc_result.get("failure_stage") or "paypal_datadome_blocked"),
                message=str(fallback_ddc_result.get("message") or "浏览器降级后 DataDome 滑块/风控仍未通过"),
            )
        )

    ensure_captcha_bypass(api)
    authorize_result = run_paypal_authorize_flow(
        api,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        paypal_ba_token=fallback_ba_token,
        credentials=normalize_paypal_credentials(paypal_email, paypal_password),
        signup_profile=build_paypal_signup_profile(
            paypal_email=paypal_email,
            paypal_password=paypal_password,
            billing_payload=signup_billing_payload,
            paypal_country=paypal_country,
            sms_url=sms_url,
            otp_channel=otp_channel,
            phone_accounts=phone_accounts,
            paypal_card_number=paypal_card_number,
            paypal_card_expiry=paypal_card_expiry,
            paypal_card_cvv=paypal_card_cvv,
        ),
        session_id=session_id,
        screenshot_paths=screenshot_paths,
        timeout_seconds=paypal_authorize_timeout_seconds(timeout_seconds),
        is_cancelled=is_cancelled,
        on_progress=on_progress,
        phone_accounts=phone_accounts,
    )
    if authorize_result:
        return preserve_roxybrowser_on_failure(authorize_result)
    return preserve_roxybrowser_on_failure(
        wait_for_paypal_result(
            api,
            checkout_url=checkout_url,
            session_id=session_id,
            screenshot_paths=screenshot_paths,
            timeout_seconds=paypal_result_timeout_seconds(timeout_seconds),
            is_cancelled=is_cancelled,
            on_progress=on_progress,
            autofill_enabled=False,
            autofill_payload=None,
        )
    )


def handle_paypal_protocol_mode_dispatch(
    api: Any,
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
    is_cancelled,
    autofill_enabled: bool,
    autofill_payload: dict[str, Any] | None,
    session_id: str,
    screenshot_paths: list[str],
    fallback_use_camoufox: bool,
    fallback_use_roxybrowser: bool,
    roxybrowser_workspace_id: str,
    roxybrowser_profile_id: str,
    handle_pre_extracted_checkout_without_ba: Callable[..., dict[str, Any] | None],
    build_result: Callable[..., dict[str, Any]],
    handle_protocol_flow_dispatch: Callable[..., dict[str, Any]],
    paypal_protocol_needs_browser_fallback: Callable[[dict[str, Any]], bool],
    handle_protocol_browser_fallback_context: Callable[..., dict[str, Any]],
    handle_protocol_browser_fallback_dispatch: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    browser_fallback_enabled: bool = True,
) -> dict[str, Any] | None:
    if not protocol_mode:
        return None

    checkout_without_ba_result = handle_pre_extracted_checkout_without_ba(
        pre_extracted,
        on_progress=on_progress,
    )
    if checkout_without_ba_result:
        result = build_result(
            str(checkout_without_ba_result.get("action") or "failed"),
            failure_stage=str(checkout_without_ba_result.get("failure_stage") or "extract_ba_link_poll"),
            message=str(
                checkout_without_ba_result.get("message") or "协议模式已获取长 checkout 链接但未拿到 PayPal BA/授权链接"
            ),
        )
        result["checkout_url"] = str(checkout_without_ba_result.get("checkout_url") or "")
        return result

    protocol_dispatch = handle_protocol_flow_dispatch(
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
        on_progress=on_progress,
    )
    signup_billing_payload = protocol_dispatch["signup_billing_payload"]
    protocol_result = protocol_dispatch["protocol_result"]
    if not paypal_protocol_needs_browser_fallback(protocol_result):
        return protocol_result
    if pre_extracted or not browser_fallback_enabled:
        return protocol_result

    fallback_context = handle_protocol_browser_fallback_context(
        protocol_result,
        paypal_mode=paypal_mode,
        paypal_country=paypal_country,
        paypal_lang=paypal_lang,
        on_progress=on_progress,
    )
    if fallback_context.get("action") == "return_protocol_result":
        return protocol_result

    return handle_protocol_browser_fallback_dispatch(
        api,
        fallback_context=fallback_context,
        fallback_approve_url=str(fallback_context.get("paypal_approve_url") or ""),
        fallback_ba_token=str(fallback_context.get("ba_token") or ""),
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
        on_progress=on_progress,
    )


def handle_paypal_signup_stop_before_otp_authorize_result(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state.get("_stop_before_signup_otp"):
        return None
    return {
        "action": "needs_review",
        "screenshot_label": "paypal-signup-before-otp",
        "failure_stage": "paypal_wait_signup_otp",
        "message": "PayPal 注册表单已提交，已按调试开关停在手机验证码输入前",
    }


def paypal_signup_stop_before_otp_result_fields(
    stop_before_otp_result: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        str(stop_before_otp_result.get("action") or "needs_review"),
        str(stop_before_otp_result.get("screenshot_label") or "paypal-signup-before-otp"),
        str(stop_before_otp_result.get("failure_stage") or "paypal_wait_signup_otp"),
        str(stop_before_otp_result.get("message") or "PayPal 注册表单已提交，已按调试开关停在手机验证码输入前"),
    )


def handle_paypal_signup_flow_failure_authorize_result(
    *,
    ok: bool,
    error: str,
    otp_phone_lock_key: str,
    release_otp_phone_lock: Callable[..., None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if ok:
        return None
    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    return {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-signup-failed",
        "failure_stage": "paypal_signup",
        "message": error,
    }


def paypal_signup_flow_failure_result_fields(
    signup_failure_result: dict[str, Any],
    *,
    fallback_error: str,
) -> tuple[str, str, str, str, str]:
    return (
        str(signup_failure_result.get("otp_phone_lock_key") or ""),
        str(signup_failure_result.get("action") or "failed"),
        str(signup_failure_result.get("screenshot_label") or "paypal-signup-failed"),
        str(signup_failure_result.get("failure_stage") or "paypal_signup"),
        str(signup_failure_result.get("message") or fallback_error),
    )


def handle_paypal_signup_login_redirect_authorize_result(
    login_redirect_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not login_redirect_result:
        return None
    action = login_redirect_result.get("action")
    if action == "continue":
        return {
            "action": "continue",
            "signup_login_redirect_count": int(login_redirect_result.get("signup_login_redirect_count") or 0),
            "signup_email_submitted": bool(login_redirect_result.get("signup_email_submitted")),
            "signup_email_submitted_at": float(login_redirect_result.get("signup_email_submitted_at") or 0),
            "signup_form_submitted": bool(login_redirect_result.get("signup_form_submitted")),
            "signup_submitted_at": float(login_redirect_result.get("signup_submitted_at") or 0),
        }
    if action == "failed":
        return {
            "action": "failed",
            "screenshot_label": str(login_redirect_result.get("screenshot_label") or "paypal-signup-login-page"),
            "failure_stage": "paypal_signup",
            "message": str(
                login_redirect_result.get("message") or "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单"
            ),
        }
    return None


def paypal_signup_login_redirect_continue_values(
    login_redirect_action: dict[str, Any],
) -> tuple[int, bool, float, bool, float]:
    return (
        int(login_redirect_action.get("signup_login_redirect_count") or 0),
        bool(login_redirect_action.get("signup_email_submitted")),
        float(login_redirect_action.get("signup_email_submitted_at") or 0),
        bool(login_redirect_action.get("signup_form_submitted")),
        float(login_redirect_action.get("signup_submitted_at") or 0),
    )


def paypal_signup_login_redirect_failed_result_fields(
    login_redirect_action: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        str(login_redirect_action.get("action") or "failed"),
        str(login_redirect_action.get("screenshot_label") or "paypal-signup-login-page"),
        str(login_redirect_action.get("failure_stage") or "paypal_signup"),
        str(login_redirect_action.get("message") or "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单"),
    )


def handle_paypal_signup_stuck_recover_authorize_result(
    stuck_recover_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not stuck_recover_result:
        return None
    action = stuck_recover_result.get("action")
    if action == "failed":
        return {
            "action": "failed",
            "screenshot_label": str(stuck_recover_result.get("screenshot_label") or "paypal-signup-email-timeout"),
            "failure_stage": "paypal_signup",
            "message": str(stuck_recover_result.get("message") or "等待 PayPal 注册表单加载超时"),
        }
    if action == "continue":
        return {
            "action": "continue",
            "signup_email_submitted": bool(stuck_recover_result.get("signup_email_submitted")),
            "signup_email_submitted_at": float(stuck_recover_result.get("signup_email_submitted_at") or 0),
        }
    return None


def paypal_signup_stuck_recover_failed_result_fields(
    stuck_recover_action: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        str(stuck_recover_action.get("action") or "failed"),
        str(stuck_recover_action.get("screenshot_label") or "paypal-signup-email-timeout"),
        str(stuck_recover_action.get("failure_stage") or "paypal_signup"),
        str(stuck_recover_action.get("message") or "等待 PayPal 注册表单加载超时"),
    )


def paypal_signup_stuck_recover_continue_values(
    stuck_recover_action: dict[str, Any],
) -> tuple[bool, float]:
    return (
        bool(stuck_recover_action.get("signup_email_submitted")),
        float(stuck_recover_action.get("signup_email_submitted_at") or 0),
    )


def handle_paypal_login_step_failure_authorize_result(*, ok: bool, error: str) -> dict[str, Any] | None:
    if ok:
        return None
    return {
        "action": "failed",
        "screenshot_label": "paypal-login-failed",
        "failure_stage": "paypal_login",
        "message": error,
    }


def paypal_login_step_failure_result_fields(
    login_failure_result: dict[str, Any],
    *,
    fallback_error: str,
) -> tuple[str, str, str, str]:
    return (
        str(login_failure_result.get("action") or "failed"),
        str(login_failure_result.get("screenshot_label") or "paypal-login-failed"),
        str(login_failure_result.get("failure_stage") or "paypal_login"),
        str(login_failure_result.get("message") or fallback_error),
    )


def handle_paypal_authorize_timeout(
    *,
    otp_phone_lock_key: str,
    release_otp_phone_lock: Callable[..., None],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    return {
        "action": "needs_review",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-authorize-timeout",
        "failure_stage": "paypal_authorize",
        "message": "等待 PayPal 登录/授权超时，需要人工确认",
    }


def paypal_authorize_timeout_result_fields(
    timeout_result: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    return (
        str(timeout_result.get("otp_phone_lock_key") or ""),
        str(timeout_result.get("action") or "needs_review"),
        str(timeout_result.get("screenshot_label") or "paypal-authorize-timeout"),
        str(timeout_result.get("failure_stage") or "paypal_authorize"),
        str(timeout_result.get("message") or "等待 PayPal 登录/授权超时，需要人工确认"),
    )


def handle_paypal_signup_visible_state_wait(
    state: dict[str, Any],
    *,
    sleep_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    if not (state.get("email_locator") or state.get("registration_ready")):
        return None
    sleep(sleep_seconds)
    return {"action": "continue"}


def handle_paypal_authorize_idle_wait(
    *,
    sleep_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    sleep(sleep_seconds)
    return {"action": "continue"}


def handle_paypal_approve_ready(
    api: Any,
    *,
    state: dict[str, Any],
    otp_phone_lock_key: str,
    click_approve: Callable[..., bool],
    release_otp_phone_lock: Callable[..., None],
    wait_for_return: Callable[..., dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    if not state.get("approve_ready"):
        return None
    if not click_approve(api, on_progress=on_progress):
        return None
    if otp_phone_lock_key:
        release_otp_phone_lock(otp_phone_lock_key, on_progress=on_progress)
    result = wait_for_return(api, on_progress=on_progress)
    return {
        "action": "return",
        "otp_phone_lock_key": "",
        "result": result,
    }


def paypal_approve_return_values(approve_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        str(approve_result.get("otp_phone_lock_key") or ""),
        approve_result["result"],
    )


def wait_for_paypal_subscription_return(
    api: Any,
    *,
    session_id: str,
    screenshot_paths: list[str],
    timeout_seconds: int,
    settle_seconds: float,
    is_cancelled=None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    progress_event: Callable[..., dict[str, Any]],
    capture_screenshot: Callable[..., None],
    build_result: Callable[..., dict[str, Any]],
    sync_relevant_payment_page: Callable[..., Any],
    is_return_url: Callable[[str], bool],
    is_paypal_host: Callable[[str], bool],
    classify_paypal_checkout_state: Callable[[str, str], dict[str, Any] | None],
    body_excerpt: BodyExcerpt,
    time_fn: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = time_fn() + max(1, int(timeout_seconds or 0))
    if on_progress:
        on_progress(
            progress_event(
                "paypal_return_wait",
                url=getattr(api.page, "url", ""),
                timeout_seconds=int(timeout_seconds or 0),
            )
        )
    while time_fn() < deadline:
        if callable(is_cancelled) and is_cancelled():
            capture_screenshot(api, session_id, "paypal-cancelled", screenshot_paths)
            return build_result(
                "failed",
                failure_stage="post_submit",
                message="任务已取消",
                screenshot_paths=screenshot_paths,
            )

        sync_relevant_payment_page(api, prefer_paypal=False)
        current_url = getattr(api.page, "url", "")
        if is_return_url(current_url):
            try:
                remaining_ms = max(1000, int((deadline - time_fn()) * 1000))
                api.page.wait_for_load_state("load", timeout=min(remaining_ms, 10000))
            except Exception:
                sleep(1.0)
                continue
            sleep(settle_seconds)
            if on_progress:
                on_progress(progress_event("paypal_return_confirmed", url=current_url))
            capture_screenshot(api, session_id, "success", screenshot_paths)
            return build_result(
                "success",
                failure_stage="",
                message="PayPal 授权后已回跳 ChatGPT/OpenAI 页面，确认绑定成功",
                screenshot_paths=screenshot_paths,
            )

        if is_paypal_host(current_url):
            classified = classify_paypal_checkout_state(current_url, body_excerpt(api))
            if classified and classified.get("status") in {"failed", "needs_review"}:
                capture_screenshot(api, session_id, "paypal-authorize-failed", screenshot_paths)
                classified["screenshot_paths"] = screenshot_paths
                return classified
        sleep(1.0)

    capture_screenshot(api, session_id, "paypal-return-timeout", screenshot_paths)
    return build_result(
        "needs_review",
        failure_stage="paypal_return_timeout",
        message="PayPal 已授权，但 120 秒内未回跳 ChatGPT/OpenAI 页面，需要确认最终绑定状态",
        screenshot_paths=screenshot_paths,
    )


def suppress_address_autocomplete_ui(api: Any) -> None:
    script = """() => {
      const id = 'autotoken-hide-address-autocomplete';
      if (!document.getElementById(id)) {
        const style = document.createElement('style');
        style.id = id;
        style.textContent = [
          'iframe[src*="autocomplete-suggestions"]',
          'iframe[title*="autocomplete" i]'
        ].join(',') + '{display:none!important;pointer-events:none!important;visibility:hidden!important;}';
        document.documentElement.appendChild(style);
      }
      return true;
    }"""
    try:
        api.page.evaluate(script)
    except Exception:
        pass


def paypal_hosted_captcha_bypass_function_source(
    selectors: tuple[str, ...] | list[str] = PAYPAL_HOSTED_CAPTCHA_ARTIFACT_SELECTORS,
) -> str:
    selectors_json = ", ".join(json.dumps(selector) for selector in selectors)
    return f"""() => {{
      const sentinel = '__AUTOTOKEN_PAYPAL_HOSTED_CAPTCHA_BYPASS__';
      const styleId = 'autotoken-paypal-hosted-captcha-bypass-style';
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


def accept_checkout_terms_on_page(
    api: Any,
    *,
    progress: Callable[..., None] | None = None,
    frames: Callable[[Any], list[Any]] = iter_page_frames,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if callable(progress):
        progress("accept_checkout_terms")

    def _is_checked(locator) -> bool:
        try:
            return bool(locator.is_checked(timeout=500))
        except Exception:
            pass
        try:
            value = str(locator.get_attribute("aria-checked", timeout=500) or "").strip().lower()
            return value == "true"
        except Exception:
            return False

    total = 0
    for frame in frames(api):
        try:
            locator = frame.locator('input[type="checkbox"], [role="checkbox"]')
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            checkbox = locator.nth(index)
            try:
                if not checkbox.is_visible(timeout=500) or checkbox.is_disabled(timeout=500) or _is_checked(checkbox):
                    continue
            except Exception:
                continue
            try:
                checkbox.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            checked = False
            try:
                checkbox.check(timeout=2500, force=True)
                checked = _is_checked(checkbox)
            except Exception:
                checked = False
            if not checked:
                try:
                    checkbox.click(timeout=2500, force=True)
                    sleep(0.2)
                    checked = _is_checked(checkbox)
                except Exception:
                    checked = False
            if not checked:
                try:
                    handle = checkbox.element_handle(timeout=1000)
                    if handle:
                        frame.evaluate(
                            """(node) => {
                              node.checked = true;
                              node.setAttribute('aria-checked', 'true');
                              node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                              node.dispatchEvent(new Event('input', { bubbles: true }));
                              node.dispatchEvent(new Event('change', { bubbles: true }));
                            }""",
                            handle,
                        )
                        sleep(0.2)
                        checked = _is_checked(checkbox)
                except Exception:
                    checked = False
            if checked:
                total += 1
    if total:
        if logger:
            logger.info("%s 已勾选 checkout 条款 checkbox: count=%s", log_prefix, total)
        if callable(progress):
            progress("checkout_terms_accepted", count=total)
    elif logger:
        logger.info("%s checkout 页面未发现需要勾选的条款 checkbox", log_prefix)
    return total


def body_excerpt(api: Any, limit: int = 1600) -> str:
    try:
        return api.page.locator("body").inner_text(timeout=1500)[:limit]
    except Exception:
        return ""


def body_excerpt_with_frames(
    api: Any,
    limit: int = 2000,
    *,
    frames: Callable[[Any], list[Any]] = iter_page_frames,
    main_timeout_ms: int = 1500,
    frame_timeout_ms: int = 700,
) -> str:
    chunks: list[str] = []
    page = getattr(api, "page", None)
    try:
        text = str(page.locator("body").inner_text(timeout=main_timeout_ms) or "").strip()
        if text:
            chunks.append(text)
    except Exception:
        pass
    for frame in frames(api):
        try:
            if page is not None and frame is getattr(page, "main_frame", None):
                continue
            text = str(frame.locator("body").inner_text(timeout=frame_timeout_ms) or "").strip()
            if text and text not in chunks:
                chunks.append(text)
        except Exception:
            continue
    return "\n".join(chunks)[:limit]


def sync_relevant_payment_page(
    api: Any,
    *,
    prefer_primary: bool = False,
    is_primary_url: Callable[[str], bool] | None = None,
    is_relevant_url: Callable[[str], bool] | None = None,
):
    context = getattr(api, "context", None)
    if not context:
        return getattr(api, "page", None)
    pages = list(getattr(context, "pages", []) or [])
    if not pages:
        return getattr(api, "page", None)

    is_primary_url = is_primary_url or (lambda _url: False)
    is_relevant_url = is_relevant_url or (lambda _url: False)
    if prefer_primary:
        for page in reversed(pages):
            if is_primary_url(str(getattr(page, "url", "") or "")):
                api.page = page
                return page
    for page in reversed(pages):
        url = str(getattr(page, "url", "") or "")
        if is_primary_url(url) or is_relevant_url(url):
            api.page = page
            return page
    api.page = pages[-1]
    return api.page


def is_checkout_page(api: Any, *, body_excerpt: BodyExcerpt = body_excerpt) -> bool:
    try:
        url = str(getattr(api.page, "url", "") or "").lower()
        if "/checkout/" in url or "payments" in url:
            return True
        body = body_excerpt(api, 1200).lower()
        hints = (
            "gopay",
            "payment method",
            "pay now",
            "billing address",
            "subscribe",
            "bayar",
            "otp",
        )
        return any(hint in body for hint in hints)
    except Exception:
        return False


def select_chatgpt_account_if_needed(
    api: Any,
    *,
    email: str = "",
    body_excerpt: BodyExcerpt = body_excerpt,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    safe_error_summary: Callable[[Any], str] = str,
    compact_log_text: Callable[..., str] = _safe_text,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    target_email = str(email or "").strip().lower()
    try:
        body = body_excerpt(api, 1200).lower()
    except Exception:
        body = ""
    if (
        "选择一个帐户" not in body
        and "choose an account" not in body
        and (not target_email or target_email not in body)
    ):
        return False
    script = """(targetEmail) => {
      const lower = (value) => String(value || "").toLowerCase();
      const target = lower(targetEmail);
      const nodes = Array.from(document.querySelectorAll("button, a, [role='button'], div, span"));
      const scored = [];
      for (const node of nodes) {
        const text = lower(node.innerText || node.textContent || "");
        if (!text) continue;
        const hasTarget = target && text.includes(target);
        const hasAccountHint = /choose an account|选择一个帐户|continue|继续|登录|log in/.test(text);
        if (!hasTarget && !hasAccountHint) continue;
        let clickable = node;
        for (let i = 0; i < 5 && clickable && !/^(BUTTON|A)$/.test(clickable.tagName || "") && clickable.getAttribute("role") !== "button"; i++) {
          clickable = clickable.parentElement;
        }
        if (!clickable) clickable = node;
        scored.push({ node: clickable, score: (hasTarget ? 100 : 0) + (hasAccountHint ? 10 : 0), text });
      }
      scored.sort((a, b) => b.score - a.score);
      if (!scored.length) return { clicked: false, reason: "no-candidate" };
      scored[0].node.click();
      return { clicked: true, text: scored[0].text.slice(0, 160) };
    }"""
    try:
        result = api.page.evaluate(script, target_email)
    except Exception as exc:
        if logger:
            logger.info("%s ChatGPT account chooser click failed: %s", log_prefix, safe_error_summary(exc))
        return False
    if result and result.get("clicked"):
        if logger:
            logger.info(
                "%s selected ChatGPT account in browser: %s",
                log_prefix,
                compact_log_text(result.get("text"), limit=120),
            )
        try:
            api.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            api.page.wait_for_timeout(2500)
        except Exception:
            sleep(2.5)
        return True
    if logger:
        logger.info("%s ChatGPT account chooser not clicked: %s", log_prefix, result)
    return False


def log_browser_auth_session_diag(
    api: Any,
    *,
    label: str,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    safe_error_summary: Callable[[Any], str] = str,
    compact_log_text: Callable[..., str] = _safe_text,
) -> None:
    try:
        result = api.page.evaluate(
            """async () => {
              try {
                const resp = await fetch("/api/auth/session", {
                  method: "GET",
                  credentials: "include",
                  headers: { Accept: "application/json" }
                });
                const text = await resp.text();
                let data = {};
                try { data = text ? JSON.parse(text) : {}; } catch (_) {}
                return {
                  ok: resp.ok,
                  status: resp.status,
                  accessTokenPresent: Boolean(data && data.accessToken),
                  userPresent: Boolean(data && data.user),
                  accountIdPresent: Boolean(data && (data.accountId || data.account_id)),
                  rawPrefix: text.slice(0, 80)
                };
              } catch (e) {
                return { ok: false, status: 0, error: String(e && e.message ? e.message : e) };
              }
            }"""
        )
    except Exception as exc:
        if logger:
            logger.info(
                "%s browser auth session diag failed: label=%s error=%s", log_prefix, label, safe_error_summary(exc)
            )
        return
    if logger:
        logger.info(
            "%s browser auth session diag: label=%s status=%s ok=%s access_token_present=%s user_present=%s account_id_present=%s error=%s raw=%s",
            log_prefix,
            label,
            result.get("status"),
            result.get("ok"),
            result.get("accessTokenPresent"),
            result.get("userPresent"),
            result.get("accountIdPresent"),
            safe_error_summary(result.get("error") or ""),
            compact_log_text(result.get("rawPrefix") or "", limit=80),
        )


def goto_with_retry(
    page,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int = 60000,
    attempts: int = 3,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    safe_url_summary: Callable[[Any], str] = str,
    safe_error_summary: Callable[[Any], str] = str,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return True
        except Exception as exc:
            last_error = safe_error_summary(exc)
            if logger:
                logger.info(
                    "%s browser goto failed, retrying: attempt=%s/%s url=%s error=%s",
                    log_prefix,
                    attempt,
                    attempts,
                    safe_url_summary(url),
                    last_error,
                )
            sleep(min(2.0 * attempt, 5.0))
    if logger:
        logger.info("%s browser goto exhausted: url=%s error=%s", log_prefix, safe_url_summary(url), last_error)
    return False


def open_checkout_in_page(
    api: Any,
    checkout_url: str,
    *,
    email: str = "",
    goto: Callable[..., bool],
    is_checkout: Callable[[Any], bool],
    body_excerpt: BodyExcerpt,
    extract_checkout_session_id: Callable[[str], str],
    select_account: Callable[[Any, str], bool],
    log_auth_session_diag: Callable[[Any, str], None] | None = None,
    logger: logging.Logger | None = None,
    log_prefix: str = "[payment_checkout_browser]",
    safe_error_summary: Callable[[Any], str] = str,
    safe_url_summary: Callable[[Any], str] = str,
    compact_log_text: Callable[..., str] = _safe_text,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 35.0,
) -> bool:
    last_error = ""
    try:
        if not goto(api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=3):
            raise RuntimeError("checkout goto failed")
    except Exception as exc:
        last_error = str(exc)
        checkout_page = api.context.new_page()
        api.page = checkout_page
        if not goto(checkout_page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=3):
            if logger:
                logger.info(
                    "%s checkout page goto failed: first=%s target=%s current=%s",
                    log_prefix,
                    safe_error_summary(last_error),
                    safe_url_summary(checkout_url),
                    safe_url_summary(getattr(getattr(api, "page", None), "url", "")),
                )
            return False

    if select_account(api, email) and not goto(
        api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=2
    ) and logger:
        logger.info(
            "%s checkout page retry after account selection failed: target=%s current=%s",
            log_prefix,
            safe_url_summary(checkout_url),
            safe_url_summary(getattr(api.page, "url", "")),
        )
    if log_auth_session_diag:
        log_auth_session_diag(api, "checkout")
    deadline = time.time() + timeout_seconds
    checkout_id = extract_checkout_session_id(checkout_url)
    while time.time() < deadline:
        current_url = str(getattr(api.page, "url", "") or "")
        if checkout_url in current_url or (checkout_id and checkout_id in current_url) or is_checkout(api):
            if logger:
                logger.info("%s checkout page opened: %s", log_prefix, safe_url_summary(current_url))
            return True
        if select_account(api, email) and not goto(
            api.page, checkout_url, wait_until="domcontentloaded", timeout=60000, attempts=2
        ) and logger:
            logger.info(
                "%s checkout page retry in wait loop failed: target=%s current=%s",
                log_prefix,
                safe_url_summary(checkout_url),
                safe_url_summary(getattr(api.page, "url", "")),
            )
        try:
            api.page.wait_for_timeout(500)
        except Exception:
            sleep(0.5)
    if logger:
        logger.info(
            "%s checkout page open timeout: target=%s current=%s body=%s",
            log_prefix,
            safe_url_summary(checkout_url),
            safe_url_summary(getattr(api.page, "url", "")),
            compact_log_text(body_excerpt(api, 500), limit=300),
        )
    return False
