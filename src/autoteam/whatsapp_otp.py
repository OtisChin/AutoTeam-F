"""WhatsApp Web OTP listener.

The listener keeps a dedicated WhatsApp Web browser profile open, reads visible
message text, and exposes recent OTP candidates to the GoPay polling flow.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from autoteam.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data" / "whatsapp_profile"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_RECENT_LIMIT = 20

_OTP_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_MESSAGE_HINT_RE = re.compile(
    r"gopay|gojek|openai|otp|kode|code|verification|verifikasi|hubungkan|link",
    re.IGNORECASE,
)
_LOGIN_HINT_RE = re.compile(
    r"use whatsapp on your computer|link with phone number|scan.*qr|whatsapp web",
    re.IGNORECASE,
)


def _now() -> float:
    return time.time()


def _compact(value: Any, limit: int = 300) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _extract_otp_from_text(text: str) -> str:
    raw = str(text or "")
    if not raw or not _MESSAGE_HINT_RE.search(raw):
        return ""
    matches = _OTP_RE.findall(raw)
    if not matches:
        return ""
    return str(matches[-1] or "").strip()


class WhatsAppOtpListener:
    def __init__(
        self,
        *,
        profile_dir: str | Path = DEFAULT_PROFILE_DIR,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        recent_limit: int = DEFAULT_RECENT_LIMIT,
        headless: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds or DEFAULT_POLL_INTERVAL_SECONDS))
        self.recent_limit = max(1, int(recent_limit or DEFAULT_RECENT_LIMIT))
        self.headless = bool(headless)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._login_required = False
        self._last_error = ""
        self._last_seen_at = 0.0
        self._latest: dict[str, Any] | None = None
        self._recent: list[dict[str, Any]] = []
        self._seen_keys: set[str] = set()

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._stop_event.clear()
            self._last_error = ""
            self._thread = threading.Thread(target=self._run, name="whatsapp-otp-listener", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict:
        self._stop_event.set()
        thread = None
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._running = False
            self._thread = None
        return self.status()

    def clear(self) -> dict:
        with self._lock:
            self._latest = None
            self._recent = []
            self._seen_keys = set()
            self._last_seen_at = 0.0
        return self.status()

    def status(self) -> dict:
        with self._lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            latest = dict(self._latest or {})
            return {
                "running": bool(self._running and thread_alive),
                "thread_alive": thread_alive,
                "login_required": bool(self._login_required),
                "profile_dir": str(self.profile_dir),
                "last_error": self._last_error,
                "last_seen_at": self._last_seen_at,
                "latest": latest,
                "recent_count": len(self._recent),
                "otp_url": "/otp/whatsapp/latest",
            }

    def latest_response(self, *, max_age_seconds: int = 600) -> dict:
        with self._lock:
            recent = [dict(item) for item in self._recent]
            latest = dict(self._latest or {})
            login_required = self._login_required
            running = self._running and bool(self._thread and self._thread.is_alive())
            last_error = self._last_error

        if not running:
            return {"code": 0, "msg": "WhatsApp OTP listener is not running", "data": {"code": "", "messages": recent}}
        if login_required:
            return {"code": 0, "msg": "WhatsApp Web needs login", "data": {"code": "", "messages": recent}}
        if last_error:
            logger.debug("[whatsapp-otp] last listener error: %s", last_error)

        if not latest:
            return {"code": 0, "msg": "No verification code", "data": {"code": "", "messages": recent}}
        age = max(0.0, _now() - float(latest.get("received_at") or 0))
        if max_age_seconds > 0 and age > max_age_seconds:
            return {
                "code": 0,
                "msg": "No fresh verification code",
                "data": {"code": "", "messages": recent, "latest_age_seconds": int(age)},
            }
        return {
            "code": 1,
            "msg": "ok",
            "data": {
                "code": latest.get("raw") or latest.get("code") or "",
                "otp": latest.get("code") or "",
                "source": "whatsapp",
                "received_at": latest.get("received_at"),
                "messages": recent,
            },
        }

    def _record_message(self, *, code: str, raw: str):
        code = str(code or "").strip()
        raw = _compact(raw, 500)
        if not code or not raw:
            return
        key = f"{code}|{raw}"
        with self._lock:
            if key in self._seen_keys:
                return
            item = {
                "code": code,
                "raw": raw,
                "source": "whatsapp",
                "received_at": _now(),
            }
            self._seen_keys.add(key)
            self._latest = item
            self._recent.append(item)
            self._recent = self._recent[-self.recent_limit :]
            self._last_seen_at = item["received_at"]
            if len(self._seen_keys) > self.recent_limit * 4:
                self._seen_keys = {f"{entry.get('code')}|{entry.get('raw')}" for entry in self._recent}
        logger.info("[whatsapp-otp] captured WhatsApp OTP: %s", code)

    def _run(self):
        playwright = None
        context = None
        try:
            from playwright.sync_api import sync_playwright

            with self._lock:
                self._running = True
                self._login_required = False
                self._last_error = ""

            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--disable-dev-shm-usage",
                ],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)
            logger.info("[whatsapp-otp] WhatsApp Web listener started: profile=%s", self.profile_dir)

            while not self._stop_event.is_set():
                try:
                    state = self._scrape_page(page)
                    with self._lock:
                        self._login_required = bool(state.get("login_required"))
                        self._last_error = ""
                    for message in state.get("messages") or []:
                        text = str(message or "")
                        code = _extract_otp_from_text(text)
                        if code:
                            self._record_message(code=code, raw=text)
                except Exception as exc:
                    with self._lock:
                        self._last_error = _compact(exc, 300)
                    logger.debug("[whatsapp-otp] scrape failed: %s", exc)
                self._stop_event.wait(self.poll_interval_seconds)
        except Exception as exc:
            with self._lock:
                self._last_error = _compact(exc, 500)
            logger.exception("[whatsapp-otp] listener failed")
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if playwright:
                    playwright.stop()
            except Exception:
                pass
            with self._lock:
                self._running = False
            logger.info("[whatsapp-otp] listener stopped")

    @staticmethod
    def _scrape_page(page) -> dict:
        return page.evaluate(
            """() => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none'
                  && rect.width > 0 && rect.height > 0;
              };
              const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
              const body = normalize(document.body ? document.body.innerText : '');
              const loginRequired = /Use WhatsApp on your computer|Link with phone number|Scan.*QR|WhatsApp Web/i.test(body)
                && !/Search or start new chat|Chats|Archived/i.test(body);
              const candidates = [];
              const nodes = Array.from(document.querySelectorAll('[data-pre-plain-text], [role="row"], span, div'));
              for (const el of nodes) {
                if (!visible(el)) continue;
                const text = normalize(el.innerText || el.textContent || '');
                if (!text || text.length < 8 || text.length > 800) continue;
                if (!/(gopay|gojek|openai|otp|kode|code|verification|verifikasi|hubungkan|link)/i.test(text)) continue;
                if (!/(?<!\\d)\\d{4,8}(?!\\d)/.test(text)) continue;
                candidates.push(text);
              }
              return { login_required: loginRequired, messages: Array.from(new Set(candidates)).slice(-30) };
            }"""
        )


_DEFAULT_LISTENER = WhatsAppOtpListener()


def get_default_listener() -> WhatsAppOtpListener:
    return _DEFAULT_LISTENER
