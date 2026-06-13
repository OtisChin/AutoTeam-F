"""Protocol registration bridge.

Browser registration remains the default path.  This module adapts an optional
protocol flow while keeping AutoToken's own mail providers and auth_session /
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

from autotoken.services import chatgpt_session as chatgpt_session_service

logger = logging.getLogger(__name__)


def _phone_pool_failure_action(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "release"
    if "429" in text or "too many requests" in text or "rate_limit" in text or "rate limit" in text:
        return "cooldown"
    if (
        "phone_already_registered" in text
        or "phone_number_in_use" in text
        or "手机号已注册" in text
        or "手机号已被使用" in text
    ):
        return "invalid"
    return "release"


def _load_protocol_classes():
    protocol_dir = Path(__file__).resolve().parents[1] / "_protocol_register"
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

    def __init__(
        self,
        mail_client,
        *,
        email: str = "",
        account_id: str | int | None = None,
        mailbox_factory=None,
    ):
        self.mail_client = mail_client
        self.email = str(email or "").strip()
        self.account_id = account_id
        self.mailbox_factory = mailbox_factory

    def create_mailbox(self) -> str:
        if not self.email and callable(self.mailbox_factory):
            account_id, email = self.mailbox_factory()
            self.account_id = account_id
            self.email = str(email or "").strip()
        if not self.email:
            raise RuntimeError("邮箱供应商未返回可用邮箱")
        logger.info("[协议注册] 已锁定注册邮箱: %s", self.email)
        return self.email

    def rotate_mailbox(self) -> str:
        if not callable(self.mailbox_factory):
            return self.create_mailbox()
        self.account_id = None
        self.email = ""
        return self.create_mailbox()

    def wait_for_otp(
        self,
        email: str,
        timeout: int = 180,
        issued_after: float | None = None,
        exclude_codes: set[str] | list[str] | tuple[str, ...] | None = None,
        strict_issued_after: bool = False,
    ) -> str:
        target = str(email or self.email or "").strip()
        deadline = time.time() + max(1, int(timeout or 180))
        issued_after_ts = float(issued_after or 0)
        excluded = {str(x or "").strip() for x in (exclude_codes or []) if str(x or "").strip()}
        last_seen = ""
        last_no_code_signature = ""
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
                if strict_issued_after and issued_after_ts and received_at and received_at < issued_after_ts - 5:
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
                raw = item.get("raw")
                raw_keys = sorted(raw.keys())[:12] if isinstance(raw, dict) else []
                item_keys = sorted(item.keys())[:12]
                signature = f"{item.get('id') or item.get('message_id') or ''}|{item.get('subject') or ''}|{item_keys}|{raw_keys}"
                if signature != last_no_code_signature:
                    logger.info(
                        "[协议注册] 候选邮件未解析出验证码: subject=%s received_at=%s keys=%s raw_keys=%s",
                        str(item.get("subject") or "")[:80],
                        received_at or "",
                        item_keys,
                        raw_keys,
                    )
                    last_no_code_signature = signature
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

        flow.signup = signup_wrapped

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

        flow.kickoff_otp_delivery = kickoff_wrapped


def _attach_oauth_phone_supplier(
    flow,
    *,
    provider: str | None = None,
    country: str | None = None,
    email: str = "",
    allow_hero_reuse: bool = True,
) -> None:
    provider = str(provider or "").strip().lower().replace("-", "_")
    if provider in {"herosms", "hero"}:
        provider = "hero_sms"
    if not provider:
        return
    if provider in {"pool", "phonepool", "phone_pool"}:
        provider = "phone_pool"
    if provider not in {"hero_sms", "smsbower", "phone_pool"}:
        return

    phone_state: dict[str, Any] = {"item": None, "finished": False}
    reservation_owner = str(email or f"protocol_register:{id(flow)}").strip()

    def supplier() -> dict:
        if isinstance(phone_state.get("item"), dict) and not phone_state.get("finished"):
            return phone_state["item"]
        from autotoken.auth.codex_auth import _acquire_oauth_hero_sms_phone, _acquire_oauth_smsbower_phone

        phone_state["finished"] = False
        if provider == "hero_sms":
            item, error = _acquire_oauth_hero_sms_phone(
                email=email,
                country=country,
                reservation_owner=reservation_owner,
                allow_reuse=allow_hero_reuse,
            )
        elif provider == "smsbower":
            item, error = _acquire_oauth_smsbower_phone(
                email=email,
                country=country,
                reservation_owner=reservation_owner,
                allow_reuse=True,
            )
        else:
            try:
                from autotoken.auth.oauth_phone_pool import acquire_available_phone

                item = acquire_available_phone(email)
                error = "" if item else "手机号池无可用号码"
            except Exception as exc:
                item, error = None, str(exc)
        if not item:
            raise RuntimeError(error or f"{provider} 未返回可用号码")
        item.setdefault("source", provider)
        phone_state["item"] = item
        logger.info("[协议注册] add-phone 已取号: provider=%s phone=%s", provider, item.get("phone_number") or item.get("phone"))
        return item

    def otp_reader(phone_item: dict, timeout: int) -> str:
        activation = phone_item.get("activation")
        if not activation or not hasattr(activation, "wait_code"):
            sms_url = str(phone_item.get("sms_url") or "").strip()
            if not sms_url:
                return ""
            from autotoken.auth.codex_auth import _make_phone_otp_provider

            return str(_make_phone_otp_provider(sms_url)() or "").strip()
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
        bound_email = str(
            phone_item.get("bound_email")
            or getattr(getattr(flow, "result", None), "email", "")
            or email
            or ""
        ).strip()
        source = str(phone_item.get("source") or provider).lower()
        if source == "hero_sms":
            from autotoken.auth.codex_auth import _mark_oauth_hero_sms_bound, _release_oauth_hero_sms_phone

            if phone_item.get("phone_first_signup"):
                _release_oauth_hero_sms_phone(
                    phone_item,
                    email=bound_email,
                    finish=True,
                    reason="phone_first_signup_success",
                    reservation_owner=reservation_owner,
                )
            else:
                _mark_oauth_hero_sms_bound(phone_item, email=bound_email)
        elif source == "smsbower":
            from autotoken.auth.codex_auth import _mark_oauth_smsbower_bound, _release_oauth_sms_activation_phone

            if phone_item.get("phone_first_signup"):
                _release_oauth_sms_activation_phone(
                    phone_item,
                    email=bound_email,
                    finish=True,
                    reason="phone_first_signup_success",
                    reservation_owner=reservation_owner,
                )
            else:
                _mark_oauth_smsbower_bound(phone_item, email=bound_email)
        else:
            from autotoken.auth.oauth_phone_pool import mark_phone_bound

            mark_phone_bound(str(phone_item.get("id") or ""), bound_email)

    def failure(phone_item: dict, reason: str = "") -> None:
        if phone_state.get("finished"):
            return
        phone_state["finished"] = True
        source = str(phone_item.get("source") or provider).lower()
        if source == "hero_sms":
            from autotoken.auth.codex_auth import _release_oauth_hero_sms_phone

            phone_first_used = bool(phone_item.get("phone_first_openai_used") or phone_item.get("phone_first_signup"))
            _release_oauth_hero_sms_phone(
                phone_item,
                email=email,
                cancel=phone_first_used,
                reason=reason or "protocol_oauth_failed",
                reservation_owner=reservation_owner,
            )
        elif source == "smsbower":
            from autotoken.auth.codex_auth import _release_oauth_sms_activation_phone

            phone_first_used = bool(phone_item.get("phone_first_openai_used") or phone_item.get("phone_first_signup"))
            _release_oauth_sms_activation_phone(
                phone_item,
                email=email,
                cancel=phone_first_used,
                reason=reason or "protocol_oauth_failed",
                reservation_owner=reservation_owner,
            )
        else:
            from autotoken.auth.oauth_phone_pool import (
                mark_phone_cooldown,
                mark_phone_invalid,
                release_phone_reservation,
            )

            item_id = str(phone_item.get("id") or "")
            if phone_item.get("phone_first_openai_used") or phone_item.get("phone_first_signup"):
                mark_phone_invalid(item_id, reason or "phone_first_openai_used")
                logger.info("[协议注册] phone_pool 注册手机号已标记无效: phone=%s reason=%s", phone_item.get("phone_number") or phone_item.get("phone"), reason)
                phone_state["item"] = None
                phone_state["finished"] = False
                return
            action = _phone_pool_failure_action(reason)
            if action == "cooldown":
                mark_phone_cooldown(item_id, reason or "rate_limited")
                logger.info("[协议注册] phone_pool 号码已冷却: phone=%s reason=%s", phone_item.get("phone_number") or phone_item.get("phone"), reason)
            elif action == "invalid":
                mark_phone_invalid(item_id, reason or "phone_unusable")
                logger.info("[协议注册] phone_pool 号码已标记无效: phone=%s reason=%s", phone_item.get("phone_number") or phone_item.get("phone"), reason)
            else:
                release_phone_reservation(item_id, email)
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
    oauth_access_token = str(data.get("access_token") or "").strip()
    chatgpt_access_token = str(data.get("chatgpt_access_token") or "").strip()
    session_access_token = chatgpt_access_token or oauth_access_token
    refresh_token = str(data.get("refresh_token") or "").strip()
    id_token = str(data.get("id_token") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    cookie_header = str(data.get("cookie_header") or "").strip()
    email = str(data.get("email") or "").strip()
    account_id = str(data.get("account_id") or "").strip()
    plan_type = str(data.get("plan_type") or "").strip().lower()
    session = {
        "accessToken": session_access_token,
        "access_token": session_access_token,
        "chatgpt_access_token": chatgpt_access_token,
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
    if account_id:
        session["accountId"] = account_id
        session["account"] = {"id": account_id}
    if plan_type:
        session.setdefault("account", {})["planType"] = plan_type
    payload = {
        "status": 200 if session_access_token or oauth_access_token else 0,
        "data": session,
        "raw": "",
        "email": email,
        "auth_context": {
            "cookie_header": cookie_header,
            "device_id": device_id,
            "oai_device_id": device_id,
        },
    }
    if oauth_access_token and refresh_token:
        try:
            from autotoken.auth.codex_auth import _build_bundle_from_token_response

            payload["codex_oauth_bundle"] = _build_bundle_from_token_response(
                {
                    "access_token": oauth_access_token,
                    "refresh_token": refresh_token,
                    "id_token": id_token,
                    "expires_in": 3600,
                },
                fallback_email=email,
            )
            bundle = payload["codex_oauth_bundle"]
            if account_id and not str(bundle.get("account_id") or "").strip():
                bundle["account_id"] = account_id
            bundle_plan = str(bundle.get("plan_type") or "").strip().lower()
            if plan_type and bundle_plan in {"", "unknown"}:
                bundle["plan_type"] = plan_type
                bundle["chatgpt_plan_type"] = plan_type
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


def phone_first_register_once(
    mail_client,
    *,
    email: str = "",
    password: str,
    account_id: str | int | None = None,
    mailbox_factory=None,
    proxy: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    progress_callback=None,
) -> tuple[bool, dict]:
    """Phone-first free registration, then bind the selected AutoToken mailbox."""

    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    if callable(progress_callback):
        flow._autotoken_progress_callback = progress_callback
    _attach_flow_stage_logs(flow)
    _attach_oauth_phone_supplier(
        flow,
        provider=oauth_phone_sms_provider or "phone_pool",
        country=oauth_phone_sms_country,
        email=email,
    )
    if password:
        flow._default_password_from_email = lambda _email: password  # type: ignore[attr-defined]
    adapter = ProtocolMailAdapter(
        mail_client,
        email=email,
        account_id=account_id,
        mailbox_factory=mailbox_factory,
    )
    logger.info(
        "[phone-first] 开始手机号注册并绑定邮箱: email=%s mailbox_id_present=%s proxy=%s provider=%s",
        email or "<手机号注册成功后创建>",
        bool(account_id),
        "enabled" if cfg.proxy else "disabled",
        oauth_phone_sms_provider or "<default>",
    )
    result = flow.run_phone_first_register(adapter)
    has_codex_tokens = bool(
        result
        and str(getattr(result, "access_token", "") or "").strip()
        and str(getattr(result, "refresh_token", "") or "").strip()
    )
    if not result or (not result.is_valid() and not has_codex_tokens):
        logger.error("[phone-first] 未返回有效 auth_session/Codex OAuth token: %s", email)
        return False, {"status": 0, "data": {}, "raw": "phone-first 未返回有效 auth_session/Codex OAuth token"}
    session_data = _session_data_from_auth_result(result)
    session_data["mailbox_email"] = adapter.email
    session_data["mailbox_account_id"] = adapter.account_id
    logger.info("[phone-first] 注册完成，已绑定邮箱: %s", adapter.email)
    return True, session_data


def _merged_auth_session_payload(session_data: dict) -> dict:
    if not isinstance(session_data, dict):
        return {}
    raw = session_data.get("data") if isinstance(session_data.get("data"), dict) else session_data
    context = session_data.get("auth_context") if isinstance(session_data.get("auth_context"), dict) else {}
    merged = {}
    if isinstance(raw, dict):
        merged.update(raw)
    merged.update({key: value for key, value in context.items() if value})
    return merged


def _auth_session_token_from_payload(payload: dict) -> str:
    token = chatgpt_session_service.session_token_from_cookie_header(str((payload or {}).get("cookie_header") or ""))
    if token:
        return token
    return str((payload or {}).get("sessionToken") or (payload or {}).get("session_token") or "").strip()


def oauth_from_auth_session_once(
    mail_client,
    *,
    session_data: dict,
    email: str = "",
    password: str = "",
    account_id: str | int | None = None,
    mailbox_factory=None,
    proxy: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    progress_callback=None,
) -> dict:
    """Pure protocol Codex OAuth from an existing ChatGPT auth_session.

    This is the dashboard counterpart of the phone->email->OAuth registration
    flow: it seeds AuthFlow with the saved ChatGPT session and lets the protocol
    OAuth path bind an email if OpenAI returns add-email.
    """

    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    if callable(progress_callback):
        flow._autotoken_progress_callback = progress_callback
    _attach_flow_stage_logs(flow)
    _attach_oauth_phone_supplier(
        flow,
        provider=oauth_phone_sms_provider or "phone_pool",
        country=oauth_phone_sms_country,
        email=email,
    )
    if password:
        flow._default_password_from_email = lambda _email: password  # type: ignore[attr-defined]

    payload = _merged_auth_session_payload(session_data)
    session_token = _auth_session_token_from_payload(payload)
    access_token = str(payload.get("accessToken") or payload.get("access_token") or "").strip()
    device_id = str(payload.get("oai_device_id") or payload.get("device_id") or "").strip()
    if not session_token and not access_token:
        raise RuntimeError(f"auth_session 缺少可复用凭证: {email or '<phone-only>'}")

    adapter = ProtocolMailAdapter(
        mail_client,
        email="" if callable(mailbox_factory) else email,
        account_id=account_id,
        mailbox_factory=mailbox_factory,
    )
    logger.info(
        "[协议补登录] 使用 auth_session 执行 Codex OAuth: email=%s mailbox_factory=%s proxy=%s provider=%s",
        email or "<phone-only>",
        bool(mailbox_factory),
        "enabled" if cfg.proxy else "disabled",
        oauth_phone_sms_provider or "<default>",
    )
    flow.from_existing_credentials(session_token, access_token, device_id)
    if email and not str(flow.result.email or "").strip():
        flow.result.email = email
    if password:
        flow.result.password = password
    if not flow.oauth_codex_rt_exchange(mail_provider=adapter):
        raise RuntimeError(f"协议 Codex OAuth 未返回 refresh_token: {email or '<phone-only>'}")
    session_payload = _session_data_from_auth_result(flow.result)
    session_payload["mailbox_email"] = adapter.email
    session_payload["mailbox_account_id"] = adapter.account_id
    logger.info("[协议补登录] Codex OAuth 完成: %s", session_payload.get("email") or adapter.email or email)
    return session_payload


def phone_only_register_once(
    *,
    password: str,
    proxy: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    progress_callback=None,
) -> tuple[bool, dict]:
    """手机号仅注册（跳过绑定邮箱和 OAuth），返回 ChatGPT Web session。"""
    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    if callable(progress_callback):
        flow._autotoken_progress_callback = progress_callback
    _attach_flow_stage_logs(flow)
    _attach_oauth_phone_supplier(
        flow,
        provider=oauth_phone_sms_provider or "phone_pool",
        country=oauth_phone_sms_country,
        email="",
    )
    if password:
        flow._default_password_from_email = lambda _email: password  # type: ignore[attr-defined]
    logger.info(
        "[phone-only] 开始手机号注册（跳过邮箱绑定和 OAuth）: proxy=%s provider=%s",
        "enabled" if cfg.proxy else "disabled",
        oauth_phone_sms_provider or "<default>",
    )
    result = flow.run_phone_first_register(mail_provider=None, phone_only=True)
    if not result or not result.is_valid():
        logger.error("[phone-only] 未返回有效 auth_session: %s", result)
        return False, {"status": 0, "data": {}, "raw": "phone-only 未返回有效 auth_session"}
    session_data = _session_data_from_auth_result(result)
    logger.info("[phone-only] 注册完成（仅手机）: %s", session_data.get("email", result.email))
    return True, session_data



def login_once(
    mail_client,
    *,
    email: str,
    password: str,
    account_id: str | int | None = None,
    proxy: str | None = None,
    oauth_phone_sms_provider: str | None = None,
    oauth_phone_sms_country: str | None = None,
    progress_callback=None,
) -> dict:
    """Pure protocol login for an existing account; returns auth_session and optional Codex OAuth bundle."""

    AuthFlow, Config = _load_protocol_classes()
    cfg = Config()
    cfg.proxy = proxy or os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or None
    flow = AuthFlow(cfg)
    if callable(progress_callback):
        flow._autotoken_progress_callback = progress_callback
    _attach_flow_stage_logs(flow)
    _attach_oauth_phone_supplier(
        flow,
        provider=oauth_phone_sms_provider,
        country=oauth_phone_sms_country,
        email=email,
    )
    adapter = ProtocolMailAdapter(mail_client, email=email, account_id=account_id)
    logger.info(
        "[协议登录] 开始协议登录 OAuth: email=%s mailbox_id_present=%s proxy=%s",
        email,
        bool(account_id),
        "enabled" if cfg.proxy else "disabled",
    )
    try:
        result = flow.run_protocol_login(adapter, email, password=password)
    except Exception:
        phone_state = getattr(flow, "_openai_phone_state", {}) or {}
        phone_item = phone_state.get("item") if isinstance(phone_state, dict) else None
        if isinstance(phone_item, dict) and not phone_state.get("finished"):
            failure = getattr(flow, "_openai_phone_failure", None)
            if callable(failure):
                try:
                    failure(phone_item, "protocol_login_exception")
                except Exception:
                    pass
        raise
    if not result or not result.is_valid():
        raise RuntimeError(f"协议登录未返回有效 auth_session: {email}")
    payload = _session_data_from_auth_result(result)
    if not payload.get("codex_oauth_bundle"):
        logger.warning("[协议登录] 协议登录完成但未直接生成 CPA OAuth bundle: %s", email)
    else:
        logger.info("[协议登录] 协议登录已生成 CPA OAuth bundle: %s", email)
    return payload
