"""Official ChatGPT Security UI executor for Authenticator App / TOTP setup."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from autotoken.core.redaction import safe_email_summary
from autotoken.services.totp import generate_totp, parse_otpauth_uri

SECURITY_SETTINGS_URL = "https://chatgpt.com/#settings/Security"


class ChatGPT2FASetupStatus(StrEnum):
    ENABLED = "enabled"
    ALREADY_ENABLED = "already_enabled"
    RECOVERY_REQUIRED = "recovery_required"
    UNSUPPORTED = "unsupported"
    RECENT_AUTH_REQUIRED = "recent_auth_required"
    SECRET_UNAVAILABLE = "secret_unavailable"
    VERIFICATION_FAILED = "verification_failed"
    ERROR = "error"


@dataclass(frozen=True)
class ChatGPT2FASetupResult:
    status: ChatGPT2FASetupStatus
    email: str
    reason: str = ""
    masked_secret: str = ""
    issuer: str = ""
    factor_label: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {ChatGPT2FASetupStatus.ENABLED, ChatGPT2FASetupStatus.ALREADY_ENABLED}

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "email": self.email,
            "reason": self.reason,
            "masked_secret": self.masked_secret,
            "issuer": self.issuer,
            "factor_label": self.factor_label,
            "ok": self.ok,
        }


class ChatGPT2FASetupExecutor:
    """Drive the first-party ChatGPT settings UI; never calls third-party TOTP APIs."""

    def __init__(
        self,
        page: Any,
        *,
        save_metadata: Callable[..., Any] | None = None,
        mark_recovery_required: Callable[[str], Any] | None = None,
        email_code_provider: Callable[..., str] | None = None,
    ) -> None:
        self.page = page
        self.save_metadata = save_metadata
        self.mark_recovery_required = mark_recovery_required
        self.email_code_provider = email_code_provider

    def enable(
        self,
        email: str,
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
        for_time: int | float | None = None,
        assume_already_enabled: bool = False,
    ) -> ChatGPT2FASetupResult:
        target_email = str(email or "").strip().lower()
        emit = progress if callable(progress) else lambda _event: None
        try:
            emit({"stage": "totp_setup_started", "email": safe_email_summary(target_email)})
            self.page.goto(SECURITY_SETTINGS_URL, wait_until="domcontentloaded", timeout=60000)
            self._wait_for_page_idle()
            self._scroll_security_panel_to_top()

            authenticator = self._find_authenticator_control()
            if not authenticator:
                return ChatGPT2FASetupResult(
                    ChatGPT2FASetupStatus.UNSUPPORTED,
                    target_email,
                    reason="Authenticator app option not found in ChatGPT Security settings",
                )

            if assume_already_enabled and self._safe_is_checked(authenticator):
                if self.mark_recovery_required:
                    self.mark_recovery_required(target_email)
                return ChatGPT2FASetupResult(
                    ChatGPT2FASetupStatus.RECOVERY_REQUIRED,
                    target_email,
                    reason="Authenticator app already enabled but local TOTP secret is unavailable",
                )

            recent_auth_started_at = time.time()
            self._safe_click(authenticator)
            self._wait_for_page_idle()

            if "email-verification" in str(getattr(self.page, "url", "")):
                if not self._complete_recent_auth_email_verification(target_email, issued_after=recent_auth_started_at):
                    return ChatGPT2FASetupResult(
                        ChatGPT2FASetupStatus.RECENT_AUTH_REQUIRED,
                        target_email,
                        reason="OpenAI recent-auth email verification is required before enabling TOTP",
                    )
                self.page.goto(SECURITY_SETTINGS_URL, wait_until="domcontentloaded", timeout=60000)
                self._wait_for_page_idle()
                self._scroll_security_panel_to_top()
                authenticator = self._find_authenticator_control()
                if not authenticator:
                    return ChatGPT2FASetupResult(
                        ChatGPT2FASetupStatus.UNSUPPORTED,
                        target_email,
                        reason="Authenticator app option not found after recent-auth verification",
                    )
                self._safe_click(authenticator)
                self._wait_for_page_idle()

            otpauth_uri = self._extract_otpauth_uri()
            if not otpauth_uri:
                if self._totp_enabled():
                    if self.mark_recovery_required:
                        self.mark_recovery_required(target_email)
                    return ChatGPT2FASetupResult(
                        ChatGPT2FASetupStatus.RECOVERY_REQUIRED,
                        target_email,
                        reason="Authenticator app is enabled but the setup secret was not available",
                    )
                return ChatGPT2FASetupResult(ChatGPT2FASetupStatus.SECRET_UNAVAILABLE, target_email)

            metadata = parse_otpauth_uri(otpauth_uri)
            code = generate_totp(metadata.secret, for_time=for_time, period=metadata.period, digits=metadata.digits)
            self._fill_verification_code(code)
            self._click_verify()
            self._wait_for_page_idle()

            if not self._totp_enabled():
                return ChatGPT2FASetupResult(
                    ChatGPT2FASetupStatus.VERIFICATION_FAILED,
                    target_email,
                    reason="Authenticator app verification was not confirmed by the Security UI",
                    masked_secret=metadata.masked_secret,
                    issuer=metadata.issuer,
                    factor_label=metadata.label,
                )

            if self.save_metadata:
                self.save_metadata(
                    email=target_email,
                    secret=metadata.secret,
                    otpauth_uri=otpauth_uri,
                    issuer=metadata.issuer,
                    factor_label=metadata.label,
                    enabled_at=time.time(),
                )
            emit(
                {
                    "stage": "totp_setup_enabled",
                    "email": safe_email_summary(target_email),
                    "masked_secret": metadata.masked_secret,
                }
            )
            return ChatGPT2FASetupResult(
                ChatGPT2FASetupStatus.ENABLED,
                target_email,
                masked_secret=metadata.masked_secret,
                issuer=metadata.issuer,
                factor_label=metadata.label,
            )
        except Exception as exc:
            return ChatGPT2FASetupResult(ChatGPT2FASetupStatus.ERROR, target_email, reason=str(exc))

    def _find_authenticator_control(self):
        candidates = [
            'button[data-testid="mfa-authenticator-toggle"]',
            'xpath=//*[contains(normalize-space(.), "Authenticator app")]/ancestor::*[.//*[@role="switch"]][1]//*[@role="switch"]',
            'xpath=//*[contains(normalize-space(.), "身份验证器应用")]/ancestor::*[.//*[@role="switch"]][1]//*[@role="switch"]',
            'xpath=//*[contains(normalize-space(.), "Authenticator app")]/following::*[@role="switch"][1]',
            'xpath=//*[contains(normalize-space(.), "身份验证器应用")]/following::*[@role="switch"][1]',
            'xpath=//*[contains(normalize-space(.), "Authenticator app")]/ancestor::*[.//button][1]//button',
            'xpath=//*[contains(normalize-space(.), "身份验证器应用")]/ancestor::*[.//button][1]//button',
            'button:has-text("Authenticator app")',
            'button:has-text("身份验证器应用")',
            'button:has-text("Authenticator")',
        ]
        for selector in candidates:
            locator = self._safe_locator(selector)
            if self._locator_count(locator) > 0:
                return self._first(locator)
        for name in ("Authenticator app", "身份验证器应用"):
            locator = self._safe_get_by_role("switch", name=name)
            if self._locator_count(locator) > 0:
                return self._first(locator)
            locator = self._safe_get_by_text(name)
            if self._locator_count(locator) > 0:
                return self._first(locator)
        return None

    def _extract_otpauth_uri(self) -> str:
        deadline = time.time() + 20
        while time.time() < deadline:
            locator = self._safe_locator('a[href^="otpauth://totp/"]')
            if self._locator_count(locator) > 0:
                return str(self._first(locator).get_attribute("href") or "").strip()
            try:
                self.page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        return ""

    def _fill_verification_code(self, code: str) -> None:
        for locator in self._code_input_candidates():
            if self._locator_count(locator) <= 0:
                continue
            self._first(locator).fill(code)
            return
        raise RuntimeError("TOTP verification code input not found")

    def _click_verify(self) -> None:
        for locator in self._verify_button_candidates():
            if self._locator_count(locator) <= 0:
                continue
            self._safe_click(self._first(locator))
            return
        raise RuntimeError("TOTP verify button not found")

    def _complete_recent_auth_email_verification(self, email: str, *, issued_after: float | None = None) -> bool:
        if not callable(self.email_code_provider):
            return False
        try:
            code = str(self.email_code_provider(email, issued_after=issued_after) or "").strip()
        except TypeError:
            code = str(self.email_code_provider(email) or "").strip()
        if not code:
            return False
        self._fill_verification_code(code)
        clicked = False
        for locator in self._continue_button_candidates():
            if self._locator_count(locator) <= 0:
                continue
            self._safe_click(self._first(locator))
            clicked = True
            break
        if not clicked:
            try:
                self.page.keyboard.press("Enter")
            except Exception:
                pass
        self._wait_for_page_idle()
        deadline = time.time() + 30
        while time.time() < deadline:
            if "email-verification" not in str(getattr(self.page, "url", "")):
                return True
            try:
                self.page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        return "email-verification" not in str(getattr(self.page, "url", ""))

    def _totp_enabled(self) -> bool:
        control = self._find_authenticator_control()
        return bool(control and self._safe_is_checked(control))

    def _code_input_candidates(self) -> list[Any]:
        return [
            self._safe_get_by_placeholder("输入 6 位验证码"),
            self._safe_get_by_placeholder("6-digit"),
            self._safe_get_by_label("输入 6 位验证码"),
            self._safe_get_by_label("verification code"),
            self._safe_locator('input[inputmode="numeric"]'),
            self._safe_locator('input[type="text"]'),
        ]

    def _verify_button_candidates(self) -> list[Any]:
        return [
            self._safe_get_by_role("button", name="验证"),
            self._safe_get_by_role("button", name="Verify"),
            self._safe_locator('button:has-text("验证")'),
            self._safe_locator('button:has-text("Verify")'),
        ]

    def _continue_button_candidates(self) -> list[Any]:
        return [
            self._safe_get_by_role("button", name="继续"),
            self._safe_get_by_role("button", name="Continue"),
            self._safe_locator('button:has-text("继续")'),
            self._safe_locator('button:has-text("Continue")'),
        ]

    def _wait_for_page_idle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(500)
        except Exception:
            pass

    def _scroll_security_panel_to_top(self) -> None:
        try:
            self.page.keyboard.press("Home")
        except Exception:
            pass
        try:
            self.page.evaluate(
                """() => {
                    for (const element of document.querySelectorAll('div, main, section')) {
                        const style = window.getComputedStyle(element);
                        if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && element.scrollTop > 0) {
                            element.scrollTop = 0;
                        }
                    }
                    window.scrollTo(0, 0);
                }"""
            )
        except Exception:
            pass
        try:
            self.page.wait_for_timeout(250)
        except Exception:
            pass

    def _safe_locator(self, selector: str):
        try:
            return self.page.locator(selector)
        except Exception:
            return None

    def _safe_get_by_role(self, role: str, *, name: str):
        try:
            return self.page.get_by_role(role, name=name)
        except Exception:
            return None

    def _safe_get_by_placeholder(self, placeholder: str):
        try:
            return self.page.get_by_placeholder(placeholder)
        except Exception:
            return None

    def _safe_get_by_label(self, label: str):
        try:
            return self.page.get_by_label(label)
        except Exception:
            return None

    def _safe_get_by_text(self, text: str):
        try:
            return self.page.get_by_text(text)
        except Exception:
            return None

    @staticmethod
    def _locator_count(locator: Any) -> int:
        if locator is None:
            return 0
        try:
            return int(locator.count())
        except Exception:
            return 0

    @staticmethod
    def _first(locator: Any) -> Any:
        first = getattr(locator, "first", None)
        return first() if callable(first) else first

    @staticmethod
    def _safe_click(locator: Any) -> None:
        try:
            locator.click(timeout=10000)
        except TypeError:
            locator.click()
        except Exception:
            locator.click(timeout=10000, force=True)

    @staticmethod
    def _safe_is_checked(locator: Any) -> bool:
        try:
            return bool(locator.is_checked())
        except Exception:
            pass
        try:
            return str(locator.get_attribute("aria-checked") or "").strip().lower() == "true"
        except Exception:
            return False
