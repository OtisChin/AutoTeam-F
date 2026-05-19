"""Protocol registration bridge.

Browser registration remains the default path.  This module adapts an optional
protocol flow while keeping AutoTeam's own mail providers and auth_session /
account storage as the source of truth.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _candidate_protocol_dirs() -> list[Path]:
    raw = os.getenv("AUTOTEAM_PROTOCOL_REGISTER_DIR", "").strip()
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw))
    candidates.extend(
        [
            Path(__file__).resolve().parents[2] / "protocol_register",
            Path(__file__).resolve().parent / "protocol_register",
        ]
    )
    return candidates


def _load_protocol_classes():
    protocol_dir = next((path for path in _candidate_protocol_dirs() if (path / "auth_flow.py").exists()), None)
    if not protocol_dir:
        searched = ", ".join(str(path) for path in _candidate_protocol_dirs())
        raise RuntimeError(
            "协议注册模块未找到，请设置 AUTOTEAM_PROTOCOL_REGISTER_DIR。"
            f"已搜索: {searched}"
        )

    protocol_dir_str = str(protocol_dir)
    if protocol_dir_str not in sys.path:
        sys.path.insert(0, protocol_dir_str)
    auth_flow = importlib.import_module("auth_flow")
    config_mod = importlib.import_module("config")
    return auth_flow.AuthFlow, config_mod.Config


def _parse_message_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts / 1000 if ts > 10_000_000_000 else ts
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        return _parse_message_ts(int(text))
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(text.replace("Z", "+0000"), fmt).timestamp()
        except Exception:
            continue
    return 0.0


def _email_received_at(email_data: dict) -> float:
    if not isinstance(email_data, dict):
        return 0.0
    for key in (
        "received_at",
        "receive_time",
        "receivedAt",
        "create_time",
        "createTime",
        "date",
        "time",
        "timestamp",
        "code_time",
    ):
        ts = _parse_message_ts(email_data.get(key))
        if ts:
            return ts
    raw = email_data.get("raw")
    if isinstance(raw, dict):
        for key in ("received_at", "receive_time", "receivedAt", "create_time", "createTime", "date", "time", "timestamp", "code_time"):
            ts = _parse_message_ts(raw.get(key))
            if ts:
                return ts
    return 0.0


class ProtocolMailAdapter:
    """Adapter expected by the referenced AuthFlow."""

    def __init__(self, mail_client, *, email: str, account_id: str | int | None = None):
        self.mail_client = mail_client
        self.email = str(email or "").strip()
        self.account_id = account_id

    def create_mailbox(self) -> str:
        return self.email

    def wait_for_otp(self, email: str, timeout: int = 180, issued_after: float | None = None) -> str:
        target = str(email or self.email or "").strip()
        deadline = time.time() + max(1, int(timeout or 180))
        issued_after_ts = float(issued_after or 0)
        last_seen = ""
        while time.time() < deadline:
            try:
                try:
                    emails = self.mail_client.search_emails_by_recipient(
                        target,
                        size=10,
                        account_id=self.account_id,
                    )
                except TypeError:
                    emails = self.mail_client.search_emails_by_recipient(target, size=10)
            except Exception as exc:
                logger.warning("[协议注册] 查询邮箱验证码失败，稍后重试: %s", exc)
                emails = []

            for item in emails or []:
                if not isinstance(item, dict):
                    continue
                received_at = _email_received_at(item)
                # Some providers return naive UTC timestamps while the local
                # process parses them as local time.  Do not discard a fresh
                # code just because the provider timestamp appears a few hours
                # earlier than the trigger time.
                if issued_after_ts and received_at and 86400 < (issued_after_ts - received_at):
                    continue
                code = ""
                try:
                    code = str(self.mail_client.extract_verification_code(item) or "").strip()
                except Exception:
                    code = ""
                if code:
                    logger.info("[协议注册] 收到邮箱验证码: %s***len=%d", code[:1], len(code))
                    return code
                if not last_seen:
                    last_seen = str(item.get("subject") or item.get("text") or item.get("content") or "")[:180]

            time.sleep(3)

        detail = f"未收到 OpenAI 邮箱验证码: {target}"
        if last_seen:
            detail += f"；最近邮件摘要: {last_seen}"
        raise TimeoutError(detail)


def _session_data_from_auth_result(result) -> dict:
    data = result.to_dict() if hasattr(result, "to_dict") else {}
    session_token = str(data.get("session_token") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    cookie_header = str(data.get("cookie_header") or "").strip()
    session = {
        "accessToken": access_token,
        "access_token": access_token,
        "sessionToken": session_token,
        "session_token": session_token,
        "device_id": device_id,
        "oai_device_id": device_id,
        "cookie_header": cookie_header,
        "user": {"email": str(data.get("email") or "").strip()},
    }
    return {
        "status": 200 if access_token else 0,
        "data": session,
        "raw": "",
        "auth_context": {
            "cookie_header": cookie_header,
            "device_id": device_id,
            "oai_device_id": device_id,
        },
    }


def register_once(mail_client, *, email: str, password: str, account_id: str | int | None = None, proxy: str | None = None) -> tuple[bool, dict]:
    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    if password:
        flow._default_password_from_email = lambda _email: password  # type: ignore[attr-defined]
    adapter = ProtocolMailAdapter(mail_client, email=email, account_id=account_id)
    logger.info("[协议注册] 开始协议注册: %s", email)
    result = flow.run_register(adapter)
    if not result or not result.is_valid():
        return False, {"status": 0, "data": {}, "raw": "协议注册未返回有效 auth_session"}
    return True, _session_data_from_auth_result(result)
