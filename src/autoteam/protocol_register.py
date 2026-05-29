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


def _load_protocol_classes():
    protocol_dir = Path(__file__).resolve().parent / "_protocol_register"
    if not (protocol_dir / "auth_flow.py").exists():
        raise RuntimeError(f"协议注册内置模块缺失: {protocol_dir}")
    protocol_dir_str = str(protocol_dir)
    if protocol_dir_str not in sys.path:
        sys.path.insert(0, protocol_dir_str)
    auth_flow = importlib.import_module("auth_flow")
    config_mod = importlib.import_module("config")
    logging.getLogger(auth_flow.__name__).setLevel(logging.WARNING)
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
        logger.info("[协议注册] 已锁定注册邮箱: %s", self.email)
        return self.email

    def wait_for_otp(
        self,
        email: str,
        timeout: int = 180,
        issued_after: float | None = None,
        exclude_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> str:
        target = str(email or self.email or "").strip()
        deadline = time.time() + max(1, int(timeout or 180))
        issued_after_ts = float(issued_after or 0)
        excluded = {str(x or "").strip() for x in (exclude_codes or []) if str(x or "").strip()}
        last_seen = ""
        next_wait_log_at = 0.0
        logger.info("[协议注册] 等待邮箱验证码: email=%s timeout=%ss", target, int(timeout or 180))
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

            if time.time() >= next_wait_log_at:
                logger.info("[协议注册] 正在查询邮箱验证码: email=%s matched=%d", target, len(emails or []))
                next_wait_log_at = time.time() + 15

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
                    if code in excluded:
                        logger.info("[协议注册] 跳过已使用邮箱验证码: %s***len=%d", code[:1], len(code))
                        continue
                    logger.info("[协议注册] 收到邮箱验证码: %s***len=%d", code[:1], len(code))
                    return code
                if not last_seen:
                    last_seen = str(item.get("subject") or item.get("text") or item.get("content") or "")[:180]

            time.sleep(3)

        detail = f"未收到 OpenAI 邮箱验证码: {target}"
        if last_seen:
            detail += f"；最近邮件摘要: {last_seen}"
        raise TimeoutError(detail)


def _wrap_flow_stage(flow, method_name: str, start_message: str, done_message: str | None = None):
    method = getattr(flow, method_name, None)
    if not callable(method):
        return

    def wrapped(*args, **kwargs):
        logger.info("[协议注册] %s", start_message)
        result = method(*args, **kwargs)
        if done_message:
            logger.info("[协议注册] %s", done_message)
        return result

    setattr(flow, method_name, wrapped)


def _attach_flow_stage_logs(flow):
    _wrap_flow_stage(flow, "register_password", "提交注册密码", "注册密码已提交")
    _wrap_flow_stage(flow, "send_otp", "触发邮箱验证码", "邮箱验证码已触发")
    _wrap_flow_stage(flow, "verify_otp", "提交邮箱验证码", "邮箱验证码校验通过")
    _wrap_flow_stage(flow, "create_account", "提交账号资料", "账号资料已提交")
    _wrap_flow_stage(flow, "get_auth_session", "获取 ChatGPT auth_session", "ChatGPT auth_session 已获取")

    signup = getattr(flow, "signup", None)
    if callable(signup):
        def signup_wrapped(*args, **kwargs):
            logger.info("[协议注册] 提交注册邮箱")
            result = signup(*args, **kwargs)
            logger.info("[协议注册] 邮箱提交完成，账号类型: %s", "新账号" if result else "已有账号")
            return result

        setattr(flow, "signup", signup_wrapped)

    kickoff = getattr(flow, "kickoff_otp_delivery", None)
    if callable(kickoff):
        def kickoff_wrapped(*args, **kwargs):
            reason = str(args[0] if args else kwargs.get("reason") or "").strip()
            if reason:
                logger.info("[协议注册] 触发/重发邮箱验证码: %s", reason)
            else:
                logger.info("[协议注册] 触发/重发邮箱验证码")
            result = kickoff(*args, **kwargs)
            logger.info("[协议注册] 邮箱验证码触发结果: %s", "成功" if result else "失败")
            return result

        setattr(flow, "kickoff_otp_delivery", kickoff_wrapped)


def _attach_oauth_phone_supplier(
    flow,
    *,
    provider: str | None = None,
    country: str | None = None,
    email: str = "",
) -> None:
    provider = str(provider or "").strip().lower().replace("-", "_")
    if provider in {"herosms", "hero"}:
        provider = "hero_sms"
    if provider not in {"hero_sms", "smsbower"}:
        return

    phone_state: dict[str, Any] = {"item": None, "finished": False}

    def supplier() -> dict:
        if isinstance(phone_state.get("item"), dict) and not phone_state.get("finished"):
            return phone_state["item"]
        from autoteam.codex_auth import _acquire_oauth_hero_sms_phone, _acquire_oauth_smsbower_phone

        phone_state["finished"] = False
        if provider == "hero_sms":
            item, error = _acquire_oauth_hero_sms_phone(email=email, country=country)
        else:
            item, error = _acquire_oauth_smsbower_phone(email=email, country=country)
        if not item:
            raise RuntimeError(error or f"{provider} 未返回可用号码")
        phone_state["item"] = item
        logger.info("[协议注册] add-phone 已取号: provider=%s phone=%s", provider, item.get("phone_number") or item.get("phone"))
        return item

    def otp_reader(phone_item: dict, timeout: int) -> str:
        activation = phone_item.get("activation")
        if not activation or not hasattr(activation, "wait_code"):
            return ""
        logger.info(
            "[协议注册] add-phone 等待手机验证码: provider=%s activation=%s",
            provider,
            phone_item.get("activation_id") or "",
        )
        return str(
            activation.wait_code(
                timeout_sec=max(30, int(timeout or 180)),
                label="protocol_oauth_add_phone",
                max_resends=2,
            )
            or ""
        ).strip()

    def success(phone_item: dict) -> None:
        phone_state["finished"] = True
        if provider == "hero_sms":
            from autoteam.codex_auth import _mark_oauth_hero_sms_bound

            _mark_oauth_hero_sms_bound(phone_item, email=email)
        else:
            from autoteam.codex_auth import _release_oauth_sms_activation_phone

            _release_oauth_sms_activation_phone(phone_item, finish=True, reason="protocol_oauth_success")

    def failure(phone_item: dict, reason: str = "") -> None:
        if phone_state.get("finished"):
            return
        phone_state["finished"] = True
        if provider == "hero_sms":
            from autoteam.codex_auth import _release_oauth_hero_sms_phone

            _release_oauth_hero_sms_phone(phone_item, email=email, cancel=True, reason=reason or "protocol_oauth_failed")
        else:
            from autoteam.codex_auth import _release_oauth_sms_activation_phone

            _release_oauth_sms_activation_phone(phone_item, cancel=True, reason=reason or "protocol_oauth_failed")
        phone_state["item"] = None
        phone_state["finished"] = False

    flow._openai_phone_supplier = supplier  # type: ignore[attr-defined]
    flow._openai_phone_otp_reader = otp_reader  # type: ignore[attr-defined]
    flow._openai_phone_success = success  # type: ignore[attr-defined]
    flow._openai_phone_failure = failure  # type: ignore[attr-defined]
    flow._openai_phone_state = phone_state  # type: ignore[attr-defined]


def _session_data_from_auth_result(result) -> dict:
    data = result.to_dict() if hasattr(result, "to_dict") else {}
    session_token = str(data.get("session_token") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or "").strip()
    id_token = str(data.get("id_token") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    cookie_header = str(data.get("cookie_header") or "").strip()
    email = str(data.get("email") or "").strip()
    session = {
        "accessToken": access_token,
        "access_token": access_token,
        "refreshToken": refresh_token,
        "refresh_token": refresh_token,
        "idToken": id_token,
        "id_token": id_token,
        "sessionToken": session_token,
        "session_token": session_token,
        "device_id": device_id,
        "oai_device_id": device_id,
        "cookie_header": cookie_header,
        "user": {"email": email},
    }
    payload = {
        "status": 200 if access_token else 0,
        "data": session,
        "raw": "",
        "auth_context": {
            "cookie_header": cookie_header,
            "device_id": device_id,
            "oai_device_id": device_id,
        },
    }
    if access_token and refresh_token:
        try:
            from autoteam.codex_auth import _build_bundle_from_token_response

            payload["codex_oauth_bundle"] = _build_bundle_from_token_response(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "id_token": id_token,
                    "expires_in": 3600,
                },
                fallback_email=email,
            )
        except Exception as exc:
            logger.warning("[协议注册] 构建协议 OAuth bundle 失败，仍保留 auth_session: %s", exc)
    return payload


def register_once(
    mail_client,
    *,
    email: str,
    password: str,
    account_id: str | int | None = None,
    proxy: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
) -> tuple[bool, dict]:
    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    _attach_flow_stage_logs(flow)
    _attach_oauth_phone_supplier(
        flow,
        provider=oauth_phone_sms_provider,
        country=oauth_phone_sms_country,
        email=email,
    )
    if password:
        flow._default_password_from_email = lambda _email: password  # type: ignore[attr-defined]
    adapter = ProtocolMailAdapter(mail_client, email=email, account_id=account_id)
    logger.info(
        "[协议注册] 开始协议注册: email=%s mailbox_id_present=%s proxy=%s",
        email,
        bool(account_id),
        "enabled" if cfg.proxy else "disabled",
    )
    try:
        result = flow.run_register(adapter)
    except Exception:
        phone_state = getattr(flow, "_openai_phone_state", {}) or {}
        phone_item = phone_state.get("item") if isinstance(phone_state, dict) else None
        if isinstance(phone_item, dict) and not phone_state.get("finished"):
            failure = getattr(flow, "_openai_phone_failure", None)
            if callable(failure):
                try:
                    failure(phone_item, "protocol_register_exception")
                except Exception:
                    pass
        raise
    if not result or not result.is_valid():
        logger.error("[协议注册] 协议注册未返回有效 auth_session: %s", email)
        return False, {"status": 0, "data": {}, "raw": "协议注册未返回有效 auth_session"}
    logger.info("[协议注册] 协议注册完成，已获取 auth_session: %s", email)
    return True, _session_data_from_auth_result(result)
