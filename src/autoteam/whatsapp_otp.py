"""WhatsApp OTP listener backed by a local Android emulator.

The listener polls an adb-connected emulator where WhatsApp is already logged
in, reads notification/UI text, and exposes recent OTP candidates through the
same local endpoint used by the GoPay polling flow.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from autoteam.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data" / "whatsapp_profile"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_RECENT_LIMIT = 20
DEFAULT_ADB_PATH = os.environ.get("ANDROID_ADB_PATH") or os.environ.get("ADB_PATH") or "adb"
DEFAULT_ADB_SERIAL = os.environ.get("WHATSAPP_ADB_SERIAL") or os.environ.get("ANDROID_ADB_SERIAL") or ""

_OTP_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_MESSAGE_HINT_RE = re.compile(
    r"gopay|gojek|openai|kode|verification|verifikasi|hubungkan|\botp\b|\bcode\b",
    re.IGNORECASE,
)
_OTP_LABELED_RE = re.compile(
    r"(?:\botp\b|\bkode\b|\bcode\b|verification(?:\s+code)?)[^\d]{0,32}(\d{4,8})(?!\d)",
    re.IGNORECASE,
)
_OTP_BEFORE_LABEL_RE = re.compile(
    r"(?<!\d)(\d{4,8})(?!\d)[^\n\r]{0,48}(?:\botp\b|\bkode\b|\bcode\b|verification(?:\s+code)?)",
    re.IGNORECASE,
)
_WHATSAPP_HINT_RE = re.compile(r"whatsapp|com\.whatsapp", re.IGNORECASE)


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
    labeled_matches = _OTP_LABELED_RE.findall(raw)
    if labeled_matches:
        return str(labeled_matches[-1] or "").strip()
    before_label_matches = _OTP_BEFORE_LABEL_RE.findall(raw)
    if before_label_matches:
        return str(before_label_matches[-1] or "").strip()
    return ""


class WhatsAppOtpListener:
    def __init__(
        self,
        *,
        profile_dir: str | Path = DEFAULT_PROFILE_DIR,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        recent_limit: int = DEFAULT_RECENT_LIMIT,
        headless: bool = False,
        adb_path: str = DEFAULT_ADB_PATH,
        adb_serial: str = DEFAULT_ADB_SERIAL,
    ):
        # Kept for backward-compatible API/status shape; no browser profile is used.
        self.profile_dir = Path(profile_dir)
        self.headless = bool(headless)
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds or DEFAULT_POLL_INTERVAL_SECONDS))
        self.recent_limit = max(1, int(recent_limit or DEFAULT_RECENT_LIMIT))
        self.adb_path = str(adb_path or DEFAULT_ADB_PATH)
        self.adb_serial = str(adb_serial or "").strip()
        self._resolved_serial = ""
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
            self._stop_event.clear()
            self._last_error = ""
            self._resolved_serial = ""
            self._thread = threading.Thread(target=self._run, name="whatsapp-adb-otp-listener", daemon=True)
            self._thread.start()
        return self._wait_for_start_status()

    def _wait_for_start_status(self, *, timeout_seconds: float = 3.0) -> dict:
        deadline = _now() + max(0.0, float(timeout_seconds or 0))
        while _now() < deadline:
            status = self.status()
            with self._lock:
                resolved = bool(self._resolved_serial)
            if resolved or status.get("last_error") or not status.get("thread_alive"):
                return status
            time.sleep(0.05)
        return self.status()

    def stop(self) -> dict:
        self._stop_event.set()
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
                "adb_path": self.adb_path,
                "adb_serial": self._resolved_serial or self.adb_serial,
                "last_error": self._last_error,
                "last_seen_at": self._last_seen_at,
                "latest": latest,
                "latest_otp": latest.get("code") or "",
                "recent_count": len(self._recent),
                "otp_url": "/otp/whatsapp/latest",
                "source": "android_emulator",
            }

    def latest_response(self, *, max_age_seconds: int = 600) -> dict:
        with self._lock:
            recent = [dict(item) for item in self._recent]
            latest = dict(self._latest or {})
            running = self._running and bool(self._thread and self._thread.is_alive())
            last_error = self._last_error

        if not running:
            return {"code": 0, "msg": "WhatsApp Android listener is not running", "data": {"code": "", "messages": recent}}
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
                "source": "whatsapp_android",
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
                "source": "whatsapp_android",
                "received_at": _now(),
            }
            self._seen_keys.add(key)
            self._latest = item
            self._recent.append(item)
            self._recent = self._recent[-self.recent_limit :]
            self._last_seen_at = item["received_at"]
            if len(self._seen_keys) > self.recent_limit * 4:
                self._seen_keys = {f"{entry.get('code')}|{entry.get('raw')}" for entry in self._recent}
        logger.info("[whatsapp-otp] captured WhatsApp Android OTP: %s", code)

    def _adb_base_command(self) -> list[str]:
        command = [self.adb_path]
        serial = self._resolved_serial or self.adb_serial
        if serial:
            command += ["-s", serial]
        return command

    def _run_adb(self, args: list[str], *, timeout: int = 10) -> str:
        command = self._adb_base_command() + args
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode != 0:
            raise RuntimeError(_compact(output or f"adb exited {proc.returncode}", 500))
        return output

    def _resolve_device(self) -> str:
        command = [self.adb_path, "devices"]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if proc.returncode != 0:
            raise RuntimeError(_compact((proc.stdout or "") + (proc.stderr or ""), 500) or "adb devices failed")
        devices: list[str] = []
        for line in (proc.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        wanted = self.adb_serial
        if wanted:
            if wanted not in devices:
                raise RuntimeError(f"未找到指定 Android 模拟器: {wanted}; 当前 devices={devices}")
            return wanted
        if not devices:
            raise RuntimeError("未发现 adb 设备，请确认模拟器已启动且 adb devices 可见")
        if len(devices) > 1:
            raise RuntimeError(f"发现多个 adb 设备，请设置 WHATSAPP_ADB_SERIAL 指定一个: {devices}")
        return devices[0]

    def _run(self):
        try:
            with self._lock:
                self._running = True
                self._login_required = False
                self._last_error = ""

            self._resolved_serial = self._resolve_device()
            logger.info("[whatsapp-otp] Android emulator listener started: serial=%s adb=%s", self._resolved_serial, self.adb_path)

            while not self._stop_event.is_set():
                try:
                    for message in self._scrape_device():
                        code = _extract_otp_from_text(message)
                        if code:
                            self._record_message(code=code, raw=message)
                    with self._lock:
                        self._last_error = ""
                except Exception as exc:
                    with self._lock:
                        self._last_error = _compact(exc, 500)
                    logger.debug("[whatsapp-otp] Android scrape failed: %s", exc)
                self._stop_event.wait(self.poll_interval_seconds)
        except Exception as exc:
            with self._lock:
                self._last_error = _compact(exc, 500)
            logger.exception("[whatsapp-otp] Android listener failed")
        finally:
            with self._lock:
                self._running = False
            logger.info("[whatsapp-otp] Android listener stopped")

    def _scrape_device(self) -> list[str]:
        messages: list[str] = []
        try:
            dumpsys_text = self._run_adb(["shell", "dumpsys", "notification", "--noredact"], timeout=12)
        except Exception as exc:
            logger.debug("[whatsapp-otp] dumpsys --noredact failed, retrying without it: %s", exc)
            dumpsys_text = self._run_adb(["shell", "dumpsys", "notification"], timeout=12)
        messages.extend(self._extract_candidates_from_blob(dumpsys_text))

        if not messages:
            try:
                self._run_adb(["shell", "uiautomator", "dump", "/sdcard/autoteam_whatsapp.xml"], timeout=8)
                ui_text = self._run_adb(["shell", "cat", "/sdcard/autoteam_whatsapp.xml"], timeout=8)
                messages.extend(self._extract_candidates_from_blob(ui_text))
            except Exception as exc:
                logger.debug("[whatsapp-otp] UI fallback failed: %s", exc)

        unique: list[str] = []
        seen: set[str] = set()
        for message in messages:
            normalized = _compact(message, 800)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique[-30:]

    @staticmethod
    def _extract_candidates_from_blob(blob: str) -> list[str]:
        text = str(blob or "")
        if not text:
            return []
        candidates: list[str] = []
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if not _MESSAGE_HINT_RE.search(line):
                continue
            window = " ".join(lines[max(0, idx - 4) : min(len(lines), idx + 8)])
            if _MESSAGE_HINT_RE.search(window) and _OTP_RE.search(window):
                candidates.append(window)

        compact_text = _compact(text, 20000)
        if (
            compact_text.startswith("<?xml")
            and _WHATSAPP_HINT_RE.search(compact_text)
            and _MESSAGE_HINT_RE.search(compact_text)
            and _OTP_RE.search(compact_text)
        ):
            candidates.append(compact_text)
        return candidates


_DEFAULT_LISTENER = WhatsAppOtpListener()


def get_default_listener() -> WhatsAppOtpListener:
    return _DEFAULT_LISTENER
