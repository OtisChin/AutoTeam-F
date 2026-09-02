"""First-party ChatGPT TOTP setup over the HTTP protocol session."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from loguru import logger

from autotoken._protocol_register.http_client import USER_AGENT, create_http_session
from autotoken.core.redaction import safe_email_summary
from autotoken.services.chatgpt_2fa_setup import (
    ChatGPT2FASetupResult,
    ChatGPT2FASetupStatus,
)
from autotoken.services.chatgpt_session import (
    CHATGPT_SESSION_COOKIE,
    session_token_from_cookie_header,
)
from autotoken.services.totp import generate_totp, mask_totp_secret, normalize_totp_secret

_CHATGPT_ORIGIN = "https://chatgpt.com"
_AUTH_ORIGIN = "https://auth.openai.com"
_MFA_ENROLL_URL = f"{_CHATGPT_ORIGIN}/backend-api/accounts/mfa/enroll"
_MFA_ACTIVATE_URL = f"{_CHATGPT_ORIGIN}/backend-api/accounts/mfa/user/activate_enrollment"


class ChatGPT2FAProtocolSetupExecutor:
    """Enable the official Authenticator factor without launching a browser."""

    def __init__(
        self,
        *,
        session_factory: Callable[..., Any] | None = None,
        save_metadata: Callable[..., Any] | None = None,
        email_code_provider: Callable[..., str] | None = None,
        proxy_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.session_factory = session_factory or create_http_session
        self.save_metadata = save_metadata
        self.email_code_provider = email_code_provider
        self.proxy_url = str(proxy_url or "").strip() or None
        self.timeout = max(5, int(timeout or 30))

    def enable(
        self,
        email: str,
        session_data: dict[str, Any] | None,
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
        for_time: int | float | None = None,
    ) -> ChatGPT2FASetupResult:
        target_email = str(email or "").strip().lower()
        emit = progress if callable(progress) else lambda _event: None
        try:
            payload = _merged_session_payload(session_data)
            session_token = _session_token(payload)
            cookie_header = str(payload.get("cookie_header") or "").strip()
            if not session_token and not cookie_header:
                raise RuntimeError("protocol auth session is missing a reusable session credential")
            if not target_email:
                raise RuntimeError("account email is required for protocol 2FA setup")

            logger.info("[2FA] 进入2FA设置流程: email={} mode=protocol", target_email)
            emit({"stage": "totp_setup_started", "email": safe_email_summary(target_email)})
            http, device_id, user_agent = self._build_session(payload, session_token, cookie_header)
            reauth_started_at = time.time()
            auth_url = self._trigger_reauth(http, target_email, device_id, user_agent)
            self._follow_reauth(http, auth_url, user_agent)

            used_codes: set[str] = set()
            continue_url = ""
            for attempt in range(2):
                code = self._request_email_code(
                    target_email,
                    issued_after=reauth_started_at,
                    exclude_codes=used_codes,
                )
                if not code:
                    return ChatGPT2FASetupResult(
                        ChatGPT2FASetupStatus.RECENT_AUTH_REQUIRED,
                        target_email,
                        reason="OpenAI recent-auth email verification code was not available",
                    )
                used_codes.add(code)
                response = http.post(
                    f"{_AUTH_ORIGIN}/api/accounts/email-otp/validate",
                    headers=_auth_api_headers(user_agent),
                    data=json.dumps({"code": code}),
                    timeout=self.timeout,
                )
                if _response_ok(response):
                    continue_url = str(_response_json(response).get("continue_url") or "").strip()
                    if not continue_url:
                        raise RuntimeError("recent-auth OTP response did not include continue_url")
                    break
                if int(getattr(response, "status_code", 0) or 0) != 401 or attempt > 0:
                    return ChatGPT2FASetupResult(
                        ChatGPT2FASetupStatus.VERIFICATION_FAILED,
                        target_email,
                        reason=f"OpenAI recent-auth email verification failed (HTTP {_status_code(response)})",
                    )
            if not continue_url:
                return ChatGPT2FASetupResult(
                    ChatGPT2FASetupStatus.VERIFICATION_FAILED,
                    target_email,
                    reason="OpenAI recent-auth email verification did not complete",
                )

            self._follow_continue_url(http, continue_url, user_agent)
            access_token = self._fetch_refreshed_access_token(http, user_agent)
            secret, enrollment_id = self._enroll(http, access_token, device_id, user_agent, payload)
            normalized_secret = normalize_totp_secret(secret)
            code = generate_totp(normalized_secret, for_time=for_time)
            self._activate(http, access_token, device_id, user_agent, payload, enrollment_id, code)

            factor_label = target_email
            issuer = "OpenAI"
            otpauth_uri = (
                f"otpauth://totp/{quote(f'{issuer}:{factor_label}', safe='')}"
                f"?secret={quote(normalized_secret)}&issuer={quote(issuer)}"
            )
            if self.save_metadata:
                self.save_metadata(
                    email=target_email,
                    secret=normalized_secret,
                    otpauth_uri=otpauth_uri,
                    issuer=issuer,
                    factor_label=factor_label,
                    enabled_at=time.time(),
                )
            masked_secret = mask_totp_secret(normalized_secret)
            emit(
                {
                    "stage": "totp_setup_enabled",
                    "email": safe_email_summary(target_email),
                    "masked_secret": masked_secret,
                }
            )
            return ChatGPT2FASetupResult(
                ChatGPT2FASetupStatus.ENABLED,
                target_email,
                masked_secret=masked_secret,
                issuer=issuer,
                factor_label=factor_label,
            )
        except Exception as exc:
            return ChatGPT2FASetupResult(ChatGPT2FASetupStatus.ERROR, target_email, reason=str(exc))

    def _build_session(self, payload: dict[str, Any], session_token: str, cookie_header: str):
        http = self.session_factory(proxy=self.proxy_url, impersonate="chrome136")
        user_agent = str(payload.get("user_agent") or payload.get("userAgent") or USER_AGENT).strip() or USER_AGENT
        device_id = str(
            payload.get("device_id") or payload.get("oai_device_id") or payload.get("oaiDeviceId") or uuid.uuid4()
        ).strip()
        try:
            http.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"})
        except Exception:
            pass

        seen: set[str] = set()
        for raw in cookie_header.split(";"):
            if "=" not in raw:
                continue
            name, value = raw.split("=", 1)
            name, value = name.strip(), value.strip()
            if not name or not value or name in seen:
                continue
            seen.add(name)
            _set_cookie(http, name, value, domain=".chatgpt.com")
        if session_token and not any(
            name == CHATGPT_SESSION_COOKIE or name.startswith(f"{CHATGPT_SESSION_COOKIE}.") for name in seen
        ):
            _set_cookie(http, CHATGPT_SESSION_COOKIE, session_token, domain=".chatgpt.com")
        if "oai-did" not in seen:
            _set_cookie(http, "oai-did", device_id, domain=".chatgpt.com")
        return http, device_id, user_agent

    def _trigger_reauth(self, http: Any, email: str, device_id: str, user_agent: str) -> str:
        csrf_response = http.get(
            f"{_CHATGPT_ORIGIN}/api/auth/csrf",
            headers=_chatgpt_headers(user_agent, referer=f"{_CHATGPT_ORIGIN}/"),
            timeout=self.timeout,
        )
        _require_ok(csrf_response, "fetch recent-auth CSRF")
        csrf_token = str(_response_json(csrf_response).get("csrfToken") or "").strip()
        if not csrf_token:
            raise RuntimeError("recent-auth CSRF response did not include csrfToken")
        query = urlencode(
            {
                "connection": "password",
                "login_hint": email,
                "reauth": "password",
                "max_age": "0",
                "ext-oai-did": device_id,
            }
        )
        response = http.post(
            f"{_CHATGPT_ORIGIN}/api/auth/signin/openai?{query}",
            headers={
                **_chatgpt_headers(user_agent, referer=f"{_CHATGPT_ORIGIN}/"),
                "content-type": "application/x-www-form-urlencoded",
                "origin": _CHATGPT_ORIGIN,
            },
            data=urlencode(
                {
                    "callbackUrl": f"{_CHATGPT_ORIGIN}/?action=enable&factor=totp",
                    "csrfToken": csrf_token,
                    "json": "true",
                }
            ),
            timeout=self.timeout,
        )
        _require_ok(response, "start password reauthentication")
        auth_url = str(_response_json(response).get("url") or "").strip()
        if not auth_url:
            raise RuntimeError("password reauthentication response did not include authorize URL")
        return auth_url

    def _follow_reauth(self, http: Any, auth_url: str, user_agent: str) -> None:
        response = http.get(
            auth_url,
            headers=_navigate_headers(user_agent, referer=f"{_CHATGPT_ORIGIN}/"),
            allow_redirects=True,
            timeout=self.timeout,
        )
        _require_ok(response, "follow password reauthentication")

    def _request_email_code(self, email: str, *, issued_after: float, exclude_codes: set[str]) -> str:
        if not callable(self.email_code_provider):
            return ""
        try:
            value = self.email_code_provider(
                email,
                issued_after=issued_after,
                exclude_codes=set(exclude_codes),
            )
        except TypeError:
            try:
                value = self.email_code_provider(email, issued_after=issued_after)
            except TypeError:
                value = self.email_code_provider(email)
        return str(value or "").strip()

    def _follow_continue_url(self, http: Any, continue_url: str, user_agent: str) -> None:
        origin = urlparse(continue_url).netloc.lower()
        referer = f"{_AUTH_ORIGIN}/email-verification"
        headers = (
            _navigate_headers(user_agent, referer=referer)
            if "auth.openai.com" in origin
            else _chatgpt_headers(user_agent, referer=referer)
        )
        response = http.get(
            continue_url,
            headers=headers,
            allow_redirects=True,
            timeout=self.timeout,
        )
        _require_ok(response, "complete password reauthentication callback")

    def _fetch_refreshed_access_token(self, http: Any, user_agent: str) -> str:
        response = http.get(
            f"{_CHATGPT_ORIGIN}/api/auth/session",
            headers=_chatgpt_headers(user_agent, referer=f"{_CHATGPT_ORIGIN}/"),
            timeout=self.timeout,
        )
        _require_ok(response, "fetch refreshed ChatGPT session")
        token = str(_response_json(response).get("accessToken") or "").strip()
        if not token:
            raise RuntimeError("refreshed ChatGPT session did not include accessToken")
        return token

    def _enroll(
        self,
        http: Any,
        access_token: str,
        device_id: str,
        user_agent: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        response = http.post(
            _MFA_ENROLL_URL,
            headers=_mfa_headers(access_token, device_id, user_agent, payload),
            data=json.dumps({"factor_type": "totp"}),
            timeout=self.timeout,
        )
        _require_ok(response, "enroll TOTP factor")
        data = _response_json(response)
        secret = str(data.get("secret") or "").strip()
        enrollment_id = str(data.get("session_id") or "").strip()
        if not secret or not enrollment_id:
            raise RuntimeError("TOTP enrollment response was missing required fields")
        return secret, enrollment_id

    def _activate(
        self,
        http: Any,
        access_token: str,
        device_id: str,
        user_agent: str,
        payload: dict[str, Any],
        enrollment_id: str,
        code: str,
    ) -> None:
        response = http.post(
            _MFA_ACTIVATE_URL,
            headers=_mfa_headers(access_token, device_id, user_agent, payload),
            data=json.dumps({"code": code, "factor_type": "totp", "session_id": enrollment_id}),
            timeout=self.timeout,
        )
        _require_ok(response, "activate TOTP factor")
        if _response_json(response).get("success") is not True:
            raise RuntimeError("TOTP activation response did not confirm success")


def _merged_session_payload(session_data: dict[str, Any] | None) -> dict[str, Any]:
    source = session_data if isinstance(session_data, dict) else {}
    data = source.get("data") if isinstance(source.get("data"), dict) else source
    context = source.get("auth_context") if isinstance(source.get("auth_context"), dict) else {}
    merged = dict(data) if isinstance(data, dict) else {}
    merged.update({key: value for key, value in context.items() if value})
    for key in (
        "accessToken",
        "access_token",
        "sessionToken",
        "session_token",
        "cookie_header",
        "device_id",
        "oai_device_id",
        "user_agent",
        "accountId",
        "account_id",
    ):
        if source.get(key) and not merged.get(key):
            merged[key] = source[key]
    return merged


def _session_token(payload: dict[str, Any]) -> str:
    token = session_token_from_cookie_header(str(payload.get("cookie_header") or ""))
    return token or str(payload.get("sessionToken") or payload.get("session_token") or "").strip()


def _set_cookie(http: Any, name: str, value: str, *, domain: str) -> None:
    try:
        http.cookies.set(name, value, domain=domain, path="/")
    except TypeError:
        http.cookies.set(name, value)


def _chatgpt_headers(user_agent: str, *, referer: str) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": referer,
        "user-agent": user_agent,
    }


def _navigate_headers(user_agent: str, *, referer: str) -> dict[str, str]:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": referer,
        "user-agent": user_agent,
    }


def _auth_api_headers(user_agent: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": _AUTH_ORIGIN,
        "referer": f"{_AUTH_ORIGIN}/email-verification",
        "user-agent": user_agent,
    }


def _mfa_headers(
    access_token: str,
    device_id: str,
    user_agent: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    account_id = str(
        payload.get("accountId") or payload.get("account_id") or account.get("id") or account.get("account_id") or ""
    ).strip()
    headers = {
        **_chatgpt_headers(user_agent, referer=f"{_CHATGPT_ORIGIN}/"),
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "en-US",
        "origin": _CHATGPT_ORIGIN,
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


def _response_json(response: Any) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception as exc:
        raise RuntimeError("OpenAI response was not valid JSON") from exc
    return value if isinstance(value, dict) else {}


def _status_code(response: Any) -> int:
    return int(getattr(response, "status_code", 0) or 0)


def _response_ok(response: Any) -> bool:
    return 200 <= _status_code(response) < 400


def _require_ok(response: Any, action: str) -> None:
    if not _response_ok(response):
        raise RuntimeError(f"OpenAI {action} failed (HTTP {_status_code(response)})")
