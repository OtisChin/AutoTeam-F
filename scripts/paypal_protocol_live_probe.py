"""Run a guarded live PayPal no-card protocol probe.

This script performs real external actions when --yes-live is passed.
By default it creates a ChatGPT checkout session, buys a PayPal SMS
activation from PAYPAL_SMS_* config, registers a no-card PayPal account,
authorizes the BA, and waits for the Stripe checkout result. It can also
start from an already-extracted BA/link plus an explicit sms_url.
Output is redacted by default.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SECRET_KEY_RE = re.compile(r"(token|secret|cookie|authorization|password|ba_token|approve_url|checkout_url|sms_url)", re.I)
TOKEN_RE = re.compile(r"\b(?:BA|EC)-[A-Za-z0-9_-]{6,}\b|\b(?:cs|pm|seti)_[A-Za-z0-9_=-]{8,}\b")
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d\s().-]{7,}\d(?!\d)")
SUPPORTED_SMS_PROVIDERS = {"hero_sms", "smsbower", "smscode", "smscloud"}


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_envs(root: Path = ROOT, extra_env: Path | None = None) -> None:
    for path in (extra_env, root / ".env", root / "data" / ".env"):
        if path:
            _load_env_file(path)


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) < 6:
        return "<phone:redacted>" if digits else ""
    prefix = "+" if str(value or "").strip().startswith("+") else ""
    return f"{prefix}{digits[:3]}***{digits[-4:]}"


def summarize_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return "<url:redacted>"
    if not parsed.scheme or not parsed.netloc:
        return "<url:redacted>"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = URL_RE.sub(lambda match: summarize_url(match.group(0)), text)
    text = TOKEN_RE.sub("<token:redacted>", text)
    text = PHONE_RE.sub(lambda match: mask_phone(match.group(0)), text)
    return text


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                redacted[key_text] = bool(str(item or "").strip()) if not isinstance(item, (dict, list)) else "<redacted>"
            elif key_text in {"phone", "phone_number", "billing_phone", "rejected_phone"}:
                redacted[key_text] = mask_phone(str(item or ""))
            elif key_text in {"message", "error", "detail"}:
                redacted[key_text] = redact_text(item)
            else:
                redacted[key_text] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True))


def _progress(stage_prefix: str):
    def on_progress(event: dict[str, Any]) -> None:
        emit_json({"kind": "progress", "source": stage_prefix, **dict(event or {})})

    return on_progress


def _require_live_confirmation(args: argparse.Namespace) -> None:
    if args.yes_live:
        return
    raise SystemExit(
        "Refusing to run live PayPal protocol probe without --yes-live. "
        "This command creates real checkout/SMS/PayPal external state."
    )


def _normalize_sms_provider(value: str) -> str:
    provider = re.sub(r"[^a-z0-9_ -]+", "", str(value or "")).strip().lower()
    provider = provider.replace("-", "_").replace(" ", "_")
    if provider in {"hero", "herosms", "hero_sms"}:
        return "hero_sms"
    if provider in {"smsbower", "sms_bower"}:
        return "smsbower"
    if provider in {"smscode", "sms_code"}:
        return "smscode"
    if provider in {"smscloud", "sms_cloud"}:
        return "smscloud"
    return provider


def _has_any_env(*names: str) -> bool:
    return any(str(os.environ.get(name) or "").strip() for name in names)


def explicit_phone_account(args: argparse.Namespace) -> dict[str, str] | None:
    sms_url = str(getattr(args, "sms_url", "") or "").strip()
    phone_number = str(getattr(args, "phone_number", "") or "").strip()
    if not sms_url and not phone_number:
        sms_url = str(os.environ.get("PAYPAL_SMS_URL") or "").strip()
        phone_number = (
            str(os.environ.get("PAYPAL_PHONE_NUMBER") or "").strip()
            or str(os.environ.get("PAYPAL_SMS_PHONE_NUMBER") or "").strip()
            or str(os.environ.get("PAYPAL_BILLING_PHONE") or "").strip()
        )
    if not sms_url and not phone_number:
        return None
    if not sms_url or not phone_number:
        raise SystemExit("--sms-url and --phone-number must be provided together")
    return {
        "phone_number": phone_number,
        "sms_url": sms_url,
        "otp_channel": str(getattr(args, "otp_channel", "") or "sms").strip().lower() or "sms",
    }


def _sms_prereq(args: argparse.Namespace) -> dict[str, Any]:
    sms_url = str(getattr(args, "sms_url", "") or "").strip()
    phone_number = str(getattr(args, "phone_number", "") or "").strip()
    if sms_url or phone_number:
        missing = []
        if not sms_url:
            missing.append("--sms-url")
        if not phone_number:
            missing.append("--phone-number")
        return {
            "ok": not missing,
            "source": "explicit_cli",
            "provider": "",
            "missing": missing,
            "phone_number": phone_number,
            "sms_url": sms_url,
        }

    env_sms_url = str(os.environ.get("PAYPAL_SMS_URL") or "").strip()
    env_phone_number = (
        str(os.environ.get("PAYPAL_PHONE_NUMBER") or "").strip()
        or str(os.environ.get("PAYPAL_SMS_PHONE_NUMBER") or "").strip()
        or str(os.environ.get("PAYPAL_BILLING_PHONE") or "").strip()
    )
    if env_sms_url or env_phone_number:
        missing = []
        if not env_sms_url:
            missing.append("PAYPAL_SMS_URL")
        if not env_phone_number:
            missing.append("PAYPAL_PHONE_NUMBER")
        return {
            "ok": not missing,
            "source": "explicit_env",
            "provider": "explicit_env",
            "missing": missing,
            "phone_number": env_phone_number,
            "sms_url": env_sms_url,
        }

    provider = _normalize_sms_provider(os.environ.get("PAYPAL_SMS_PROVIDER", ""))
    if not provider:
        return {
            "ok": False,
            "source": "missing",
            "provider": "",
            "missing": ["--sms-url/--phone-number or PAYPAL_SMS_URL/PAYPAL_PHONE_NUMBER or PAYPAL_SMS_PROVIDER"],
        }
    if provider not in SUPPORTED_SMS_PROVIDERS:
        return {
            "ok": False,
            "source": "auto_provision",
            "provider": provider,
            "missing": ["supported PAYPAL_SMS_PROVIDER: hero_sms, smsbower, smscode, smscloud"],
        }

    provider_keys = {
        "hero_sms": ("PAYPAL_HERO_SMS_API_KEY", "PAYPAL_SMS_API_KEY"),
        "smsbower": ("PAYPAL_SMSBOWER_API_KEY", "PAYPAL_SMS_API_KEY"),
        "smscode": ("PAYPAL_SMSCODE_API_TOKEN", "PAYPAL_SMS_API_KEY"),
        "smscloud": ("PAYPAL_SMSCLOUD_XI_TOKEN", "PAYPAL_SMS_API_KEY"),
    }
    key_names = provider_keys[provider]
    missing = [] if _has_any_env(*key_names) else [" or ".join(key_names)]
    return {
        "ok": not missing,
        "source": "auto_provision",
        "provider": provider,
        "missing": missing,
    }


def pre_extracted_ba_result(args: argparse.Namespace, paypal_billing_agreement: Any) -> dict[str, Any] | None:
    approve_url = str(getattr(args, "approve_url", "") or "").strip()
    ba_token = str(getattr(args, "ba_token", "") or "").strip()
    if approve_url and not ba_token:
        ba_token = paypal_billing_agreement.paypal_protocol_extract_ba_token(approve_url)
    if not approve_url and not ba_token:
        return None
    if not ba_token:
        raise SystemExit("--ba-token is required when --approve-url does not contain a BA token")
    checkout_session_id = str(getattr(args, "checkout_session_id", "") or "").strip()
    checkout_url = str(getattr(args, "checkout_url", "") or "").strip()
    hosted_checkout_url = str(getattr(args, "hosted_checkout_url", "") or "").strip()
    if not (checkout_session_id or checkout_url or hosted_checkout_url):
        raise SystemExit(
            "Direct BA/link mode requires --checkout-session-id, --checkout-url, or --hosted-checkout-url "
            "so the probe can verify protocol payment status"
        )
    return {
        "status": "success",
        "ba_token": ba_token,
        "approve_url": approve_url,
        "checkout_session_id": checkout_session_id,
        "checkout_url": checkout_url,
        "hosted_checkout_url": hosted_checkout_url,
        "pm_id": str(getattr(args, "payment_method_id", "") or "").strip(),
    }


def check_prereqs(
    args: argparse.Namespace,
    *,
    access_token_loader=None,
    ba_token_extractor=None,
) -> dict[str, Any]:
    email = str(getattr(args, "email", "") or "").strip().lower()
    direct_ba_mode = bool(
        str(getattr(args, "approve_url", "") or "").strip()
        or str(getattr(args, "ba_token", "") or "").strip()
    )
    missing: list[str] = []
    checks: dict[str, Any] = {
        "email": bool(email),
        "live_actions": False,
    }
    if not email:
        missing.append("--email")

    if direct_ba_mode:
        checks["local_auth"] = "not_required"

        class _BillingAgreement:
            @staticmethod
            def paypal_protocol_extract_ba_token(url):
                if callable(ba_token_extractor):
                    return ba_token_extractor(url)
                return ""

        try:
            ba_result = pre_extracted_ba_result(args, _BillingAgreement)
            checks["ba_link"] = bool(ba_result and ba_result.get("ba_token"))
            checks["checkout_reference"] = bool(
                ba_result
                and (
                    ba_result.get("checkout_session_id")
                    or ba_result.get("checkout_url")
                    or ba_result.get("hosted_checkout_url")
                )
            )
        except SystemExit as exc:
            checks["ba_link"] = False
            checks["checkout_reference"] = False
            missing.append(str(exc))
    else:
        checks["ba_link"] = "will_extract"
        checks["checkout_reference"] = "will_extract"
        if email:
            try:
                access_token = access_token_loader(email) if callable(access_token_loader) else ""
            except Exception as exc:
                access_token = ""
                missing.append(f"local access token loader failed: {exc}")
            checks["local_auth"] = bool(str(access_token or "").strip())
            if not checks["local_auth"]:
                missing.append(f"local access token for {email}")
        else:
            checks["local_auth"] = False

    sms = _sms_prereq(args)
    checks["sms"] = bool(sms.get("ok"))
    missing.extend(str(item) for item in sms.get("missing") or [])

    return {
        "kind": "preflight",
        "ok": not missing,
        "mode": "direct_ba" if direct_ba_mode else "extract_ba",
        "checks": checks,
        "sms_source": sms.get("source") or "",
        "sms_provider": sms.get("provider") or "",
        "phone_number": sms.get("phone_number") or "",
        "sms_url": sms.get("sms_url") or "",
        "missing": missing,
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    from autotoken.interfaces import api as api_module
    from autotoken.payments import paypal_bind_executor
    from autotoken.services import paypal_billing_agreement, paypal_phone_pool

    _require_live_confirmation(args)
    load_envs(extra_env=Path(args.env_file) if args.env_file else None)

    email = str(args.email or "").strip().lower()
    if not email:
        raise SystemExit("--email is required")

    ba_result = pre_extracted_ba_result(args, paypal_billing_agreement)
    access_token = ""
    if ba_result is None:
        access_token = api_module._extract_account_access_token(email)
        if not access_token:
            raise SystemExit(f"No access token found for {email}; auth_session/auth_file is required")

    phone_account: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    try:
        phone_account = explicit_phone_account(args)
        if phone_account:
            emit_json({"kind": "phone_ready", "phone_number": phone_account.get("phone_number"), "sms_provider": "explicit"})
        else:
            phone_account = paypal_phone_pool.provision_paypal_phone_account_from_env(
                public_base_url=args.public_base_url,
                log=lambda message: emit_json({"kind": "log", "message": message}),
            )
            emit_json(
                {
                    "kind": "phone_ready",
                    "phone_number": phone_account.get("phone_number"),
                    "sms_provider": phone_account.get("sms_provider"),
                }
            )

        billing_payload = dict(paypal_bind_executor.DEFAULT_PAYPAL_JP_BILLING_PROFILE)
        billing_payload["country"] = args.paypal_country
        billing_payload["phone"] = str(phone_account.get("phone_number") or "")
        signup_profile = paypal_bind_executor._build_paypal_signup_profile(
            billing_payload=billing_payload,
            paypal_country=args.paypal_country,
            sms_url=str(phone_account.get("sms_url") or ""),
            otp_channel=str(phone_account.get("otp_channel") or "sms"),
        )

        if ba_result is None:
            auth_context = paypal_billing_agreement.paypal_ba_auth_context(
                email,
                access_token,
                session_context_loader=paypal_bind_executor._extract_auth_session_context,
                use_full_context=True,
                log_failure=lambda exc: emit_json({"kind": "warning", "message": f"auth context fallback: {exc}"}),
            )
            extract_access_token = str(auth_context.get("access_token") or "").strip() or access_token
            provider_proxy_url = str(args.provider_proxy_url or args.proxy_url or "").strip()
            emit_json({"kind": "stage", "stage": "extract_ba_link"})
            ba_result = paypal_bind_executor._paypal_extract_ba_link(
                **paypal_billing_agreement.paypal_ba_extract_kwargs(
                    auth_session_context=auth_context,
                    access_token=extract_access_token,
                    proxy_url=str(args.proxy_url or ""),
                    provider_proxy_url=provider_proxy_url,
                    paypal_country=args.paypal_country,
                    payment_method_country=args.payment_method_country,
                    paypal_ba_mode=args.paypal_ba_mode,
                    timeout_seconds=args.timeout_seconds,
                    is_cancelled=lambda: False,
                ),
                on_progress=_progress("ba_extract"),
            )
            emit_json({"kind": "ba_result", "result": ba_result})
            if ba_result.get("status") != "success":
                final_result = ba_result
                return ba_result
        else:
            emit_json({"kind": "ba_result", "source": "pre_extracted", "result": ba_result})

        emit_json({"kind": "stage", "stage": "paypal_protocol_signup_and_payment"})
        final_result = paypal_bind_executor._run_paypal_protocol_flow(
            email=email,
            proxy_url=str(args.proxy_url or "") or None,
            paypal_mode="create_account",
            signup_profile=signup_profile,
            phone_accounts=[phone_account],
            billing_payload=billing_payload,
            timeout_seconds=args.timeout_seconds,
            paypal_country=args.paypal_country,
            paypal_lang=args.paypal_lang,
            is_cancelled=lambda: False,
            on_progress=_progress("paypal_protocol"),
            pre_extracted=ba_result,
        )
        return final_result
    finally:
        if phone_account:
            try:
                paypal_phone_pool.close_paypal_sms_bridges(
                    [phone_account],
                    success=paypal_phone_pool.paypal_sms_bridge_success_for_result(final_result),
                )
            except Exception as exc:
                emit_json({"kind": "warning", "message": f"failed to close sms bridge: {exc}"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live PayPal JP no-card protocol registration/payment probe")
    parser.add_argument("--email", required=True, help="Local ChatGPT account email with auth_session/auth_file")
    parser.add_argument("--proxy-url", default=os.environ.get("PAYPAL_LIVE_PROXY_URL", ""), help="Proxy for ChatGPT/PayPal protocol session")
    parser.add_argument("--provider-proxy-url", default=os.environ.get("PAYPAL_LIVE_PROVIDER_PROXY_URL", ""), help="Optional US/provider-stage proxy for Stripe/PayPal BA extraction")
    parser.add_argument("--public-base-url", default=os.environ.get("AUTOTOKEN_LOCAL_BASE_URL", "http://127.0.0.1:8787"), help="Local API base URL that exposes /otp/gopay-signup/{token}")
    parser.add_argument("--paypal-country", default="JP")
    parser.add_argument("--paypal-lang", default="ja")
    parser.add_argument("--paypal-ba-mode", choices=["us", "eu", "br"], default="us")
    parser.add_argument("--payment-method-country", choices=["US", "AU", "BR"], default="US")
    parser.add_argument("--sms-url", default="", help="Use an existing SMS polling URL instead of PAYPAL_SMS_* auto-provisioning")
    parser.add_argument("--phone-number", default="", help="Phone number that belongs to --sms-url")
    parser.add_argument("--otp-channel", default="sms", choices=["sms", "whatsapp"])
    parser.add_argument("--approve-url", default="", help="Already extracted PayPal approve/pay URL")
    parser.add_argument("--ba-token", default="", help="Already extracted PayPal BA token")
    parser.add_argument("--checkout-session-id", default="", help="Stripe/OpenAI checkout session id used for final payment polling")
    parser.add_argument("--checkout-url", default="", help="OpenAI/Stripe checkout URL used for final payment polling")
    parser.add_argument("--hosted-checkout-url", default="", help="Hosted checkout URL used for final payment polling")
    parser.add_argument("--payment-method-id", default="", help="Optional Stripe PayPal payment method id")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--env-file", default="", help="Optional extra env file loaded before .env")
    parser.add_argument("--check-prereqs", action="store_true", help="Check local prerequisites without live external actions")
    parser.add_argument("--yes-live", action="store_true", help="Required: create real checkout/SMS/PayPal external state")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.check_prereqs:
            from autotoken.interfaces import api as api_module
            from autotoken.services import paypal_billing_agreement

            load_envs(extra_env=Path(args.env_file) if args.env_file else None)
            result = check_prereqs(
                args,
                access_token_loader=api_module._extract_account_access_token,
                ba_token_extractor=paypal_billing_agreement.paypal_protocol_extract_ba_token,
            )
            emit_json(result)
            return 0 if result.get("ok") else 2
        result = run_probe(args)
        emit_json({"kind": "final", "result": result})
        return 0 if isinstance(result, dict) and result.get("status") == "success" else 2
    except SystemExit:
        raise
    except Exception as exc:
        emit_json({"kind": "error", "message": str(exc), "type": exc.__class__.__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
