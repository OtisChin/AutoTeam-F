#!/usr/bin/env python3
"""PayPal Billing Agreement approval automation.

Usage:
    python main.py --ba-token BA-xxx --phone +5591980133818
"""
import argparse
import datetime as _dt
import importlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from loguru import logger
from paypal.flow import PayPalFlow
from paypal.models import generate_address, generate_card, generate_user
from paypal.proxy import build_proxy_config
from paypal.session import sanitize_for_log
from paypal.traffic_recorder import close_global_traffic_recorder, reset_global_traffic_recorder


def _smsbower_module():
    return importlib.import_module("paypal.smsbower")


def _smsbower_enabled() -> bool:
    return bool(_smsbower_module().smsbower_enabled())


def _build_smsbower_provider(enabled: bool, api_key: str | None):
    return _smsbower_module().build_smsbower_provider(
        enabled=enabled,
        api_key=api_key,
    )


def _build_sms_activate_provider(**kwargs):
    return _smsbower_module().build_sms_activate_provider(**kwargs)


def _build_hero_sms_rent_provider(**kwargs):
    return _smsbower_module().build_hero_sms_rent_provider(**kwargs)


def _normalize_paypal_sms_provider(value: object = "") -> str:
    return _smsbower_module().normalize_paypal_sms_provider(value)


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default



class SmsRecordActivation:
    def __init__(self, phone_number: str):
        self.activation_id = "sms-record-fixed"
        self.phone_number = phone_number
        self.provider_id = "sms-record"
        self.price = 0.0
        self.expires_at = time.time() + 300
        self.reused = True


class SmsRecordOtpProvider:
    """Poll a fixed SMS record URL and return the newest 6-digit PayPal OTP."""

    max_attempts = 1

    def __init__(self, phone: str, record_url: str, wait_seconds: float = 120.0, poll_interval: float = 5.0):
        self.phone = phone
        self.record_url = record_url
        self.wait_seconds = wait_seconds
        self.poll_interval = poll_interval
        self._seen_codes: set[str] = set()

    def reserve_number(self):
        return SmsRecordActivation(self.phone)

    def mark_sms_sent(self, activation) -> None:
        self._sent_at = time.time()

    def abandon(self, activation, reason: str) -> None:
        logger.warning("SMS record provider abandon reason={}", reason)

    def register_confirmation_result(self, activation, confirmed: bool) -> None:
        logger.info("SMS record provider confirmation result={}", confirmed)

    @staticmethod
    def _extract_codes(text: str) -> list[str]:
        candidates = []
        lowered = (text or "").lower()
        for m in re.finditer(r"\b(\d{6})\b", text or ""):
            window = lowered[max(0, m.start() - 120):m.end() + 120]
            score = 0 if any(item in window for item in ("paypal", "pay pal", "verification", "code")) else 1
            candidates.append((score, m.group(1), m.start()))
        candidates.sort(key=lambda item: (item[0], -item[2]))
        output = []
        for _score, code, _pos in candidates:
            if code not in output:
                output.append(code)
        return output

    def _record_payload_text_and_time(self, raw: str) -> tuple[str, float | None]:
        try:
            payload = json.loads(raw)
        except Exception:
            return raw, None
        if not isinstance(payload, dict):
            return raw, None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not isinstance(data, dict):
            return raw, None
        text = str(data.get("code") or raw)
        code_time = str(data.get("code_time") or "").strip()
        if not code_time:
            return text, None
        try:
            return text, _dt.datetime.strptime(code_time, "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            return text, None

    def wait_for_code(self, activation, timeout_seconds: float | None = None) -> str | None:
        deadline = time.time() + float(timeout_seconds or self.wait_seconds)
        sent_at = float(getattr(self, "_sent_at", 0.0) or 0.0)
        while time.time() < deadline:
            try:
                req = urllib.request.Request(self.record_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                text, code_ts = self._record_payload_text_and_time(raw)
                if sent_at and code_ts is not None and code_ts + 3 < sent_at:
                    logger.debug("SMS record code is older than this OTP request; waiting for a fresh code")
                    time.sleep(self.poll_interval)
                    continue
                for code in self._extract_codes(text):
                    if code not in self._seen_codes:
                        self._seen_codes.add(code)
                        return code
            except Exception as exc:
                logger.debug("SMS record poll soft-failed: {}", exc)
            time.sleep(self.poll_interval)
        return None

def main():
    parser = argparse.ArgumentParser(
        description="PayPal Billing Agreement Approval Automation"
    )
    parser.add_argument(
        "--ba-token", required=True,
        help="Billing Agreement token (e.g. BA-3AX328361P111131W)"
    )
    parser.add_argument(
        "--phone",
        default="",
        help="Phone number with country code (e.g. +5591980133818)"
    )
    parser.add_argument(
        "--sms-record-url",
        default=os.getenv("SMSCC_RECORD_URL", ""),
        help="Poll this fixed SMS record URL for a 6-digit PayPal OTP instead of interactive input.",
    )
    parser.add_argument(
        "--sms-record-wait",
        type=float,
        default=float(os.getenv("SMS_RECORD_WAIT_SECONDS", "120")),
        help="Seconds to wait for --sms-record-url OTP.",
    )
    parser.add_argument(
        "--sms-record-poll",
        type=float,
        default=float(os.getenv("SMS_RECORD_POLL_INTERVAL", "5")),
        help="Seconds between --sms-record-url polls.",
    )
    parser.add_argument(
        "--sms-number-wait",
        type=float,
        default=_env_float("PAYPAL_SMS_NUMBER_WAIT_SECONDS", 60.0),
        help=(
            "Seconds to wait per acquired HeroSMS/SMSBower number before "
            "abandoning it and switching to a new number. Default: 60."
        ),
    )
    parser.add_argument(
        "--country",
        default=os.getenv("PAYPAL_COUNTRY", "BR"),
        choices=[
            "BR", "US", "GB", "NL", "AU", "CA", "ID", "JP", "MX", "PH", "TH",
            "br", "us", "gb", "nl", "au", "ca", "id", "jp", "mx", "ph", "th",
        ],
        help="Buyer/onboarding country. Default: BR; use AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US for PayPal.",
    )
    parser.add_argument(
        "--smsbower",
        action="store_true",
        help="Use SMSBower to acquire and receive the PayPal SMS automatically",
    )
    parser.add_argument(
        "--smsbower-api-key",
        default=None,
        help="SMSBower API key. Defaults to SMSBOWER_API_KEY or PAYPAL_SMSBOWER_API_KEY from .env/environment",
    )
    parser.add_argument(
        "--sms-provider",
        default=os.getenv("PAYPAL_SMS_PROVIDER", ""),
        help="SMS OTP provider: sms-record, hero-sms, hero-sms-rent, smsbower, or empty/manual.",
    )
    parser.add_argument(
        "--sms-api-key",
        default=None,
        help="HeroSMS/SMSBower API key. Prefer environment variables in web runner to keep logs clean.",
    )
    parser.add_argument(
        "--sms-base-url",
        default=os.getenv("PAYPAL_SMS_BASE_URL", ""),
        help="SMS-Activate compatible API base URL.",
    )
    parser.add_argument(
        "--sms-service",
        default=os.getenv("PAYPAL_SMS_SERVICE", ""),
        help="SMS provider service code. Default: ts (PayPal).",
    )
    parser.add_argument(
        "--sms-country",
        default=os.getenv("PAYPAL_SMS_COUNTRY", ""),
        help="SMS provider country ID. Default for US: 187.",
    )
    parser.add_argument(
        "--sms-min-price",
        default=os.getenv("PAYPAL_SMS_MIN_PRICE", ""),
        help="Optional SMS provider minPrice.",
    )
    parser.add_argument(
        "--sms-max-price",
        default=os.getenv("PAYPAL_SMS_MAX_PRICE", ""),
        help="Optional SMS provider maxPrice.",
    )
    parser.add_argument(
        "--sms-preferred-price",
        default=os.getenv("PAYPAL_SMS_PREFERRED_PRICE", ""),
        help="Optional SMS provider preferred/fixed price.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--max-card-attempts",
        type=int,
        default=5,
        help="Max SignUpNewMember retries with fresh generated Visa/MasterCard when addCard fails",
    )
    parser.add_argument(
        "--max-flow-attempts",
        type=int,
        default=1,
        help="Max full-flow attempts; 1 means no full-flow retry",
    )
    parser.add_argument(
        "--max-authorize-attempts",
        type=int,
        default=3,
        help="Max authorize retries after reloading Hermes/Hagrid review context",
    )
    parser.add_argument(
        "--card-retry-delay",
        type=float,
        default=6.0,
        help="Seconds to wait before generating/submitting the next card after a card rejection",
    )
    parser.add_argument(
        "--card-retry-jitter",
        type=float,
        default=2.0,
        help="Extra random seconds added to card retry delay",
    )
    proxy_group = parser.add_mutually_exclusive_group()
    proxy_group.add_argument(
        "--proxy",
        dest="proxy_enabled",
        action="store_true",
        default=None,
        help="Enable outbound proxy from PAYPAL_PROXY_URL or PAYPAL_PROXY_POOL for this run",
    )
    proxy_group.add_argument(
        "--no-proxy",
        dest="proxy_enabled",
        action="store_false",
        help="Disable outbound proxy for this run",
    )
    parser.add_argument(
        "--proxy-index",
        type=int,
        default=None,
        help="Use a specific PAYPAL_PROXY_POOL entry (0-based). Default: random when proxy is enabled",
    )
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Use a custom/chained proxy URL or host:port:user:pass line for this run",
    )
    parser.add_argument(
        "--record-traffic",
        action="store_true",
        help="Test mode: record all program-side outbound requests/responses for offline diffing",
    )
    parser.add_argument(
        "--traffic-dir",
        default=None,
        help="Output directory for --record-traffic. Default: captures/program-paypal-YYYYMMDD-HHMMSS",
    )
    parser.add_argument(
        "--compare-roxy-capture",
        default=None,
        help="After --record-traffic run, compare program traffic with this Roxy capture dir",
    )
    parser.add_argument(
        "--fingerprint-source",
        choices=["random", "program", "python", "synthetic", "roxy", "browser", "headless", "local_headless", "playwright", "local_playwright", "auto"],
        default=None,
        help="Browser fingerprint source: random/program Python generator, roxy RoxyBrowser runtime, local headless Playwright, or auto",
    )
    parser.add_argument(
        "--datadome-mode",
        choices=["protocol", "edge", "roxy", "browser", "headless", "local_headless", "playwright", "local_playwright", "auto", "off"],
        default=None,
        help="DataDome mode: protocol edge simulation, roxy browser runtime, local headless Playwright, auto, or off",
    )
    parser.add_argument(
        "--mtr-runtime",
        choices=["python_generated", "python", "protocol", "roxy", "browser", "headless", "local_headless", "playwright", "local_playwright", "auto", "block", "off"],
        default=None,
        help="MTR sealedResult source: python_generated protocol template, roxy browser runtime, local headless Playwright, auto, block, or off",
    )
    parser.add_argument(
        "--approval-path",
        choices=["auto", "create-member-no-fi", "signup-card", "legacy"],
        default=os.getenv("PAYPAL_APPROVAL_PATH", "auto"),
        help="Approval strategy. auto uses SignUpNewMember/card; create-member-no-fi is explicit opt-in.",
    )
    parser.add_argument(
        "--risk-signals-mode",
        choices=["protocol", "python", "synthetic", "template", "roxy", "browser", "headless", "local_headless", "playwright", "local_playwright", "auto", "off"],
        default=None,
        help="Signup-context browser risk source: roxy browser runtime, local headless Playwright, auto, or off",
    )

    args = parser.parse_args()

    logger.remove()
    if args.debug:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")
    if args.datadome_mode:
        os.environ["PAYPAL_DATADOME_MODE"] = args.datadome_mode
    if args.mtr_runtime:
        os.environ["PAYPAL_MTR_RUNTIME"] = args.mtr_runtime
    if args.risk_signals_mode:
        os.environ["PAYPAL_RISK_SIGNALS_MODE"] = args.risk_signals_mode
    if args.approval_path:
        os.environ["PAYPAL_APPROVAL_PATH"] = args.approval_path.replace("-", "_")

    traffic_recorder = None
    if args.record_traffic or args.traffic_dir or args.compare_roxy_capture:
        os.environ["PAYPAL_TRAFFIC_RECORD"] = "1"
        traffic_recorder = reset_global_traffic_recorder(args.traffic_dir)
        logger.info("Program traffic recording enabled: {}", traffic_recorder.root)

    proxy_config = build_proxy_config(
        enabled=args.proxy_enabled,
        index=args.proxy_index,
        proxy_url=args.proxy_url,
    )
    sms_provider = None
    normalized_sms_provider = _normalize_paypal_sms_provider(args.sms_provider)
    if args.sms_record_url or normalized_sms_provider == "sms_record":
        if not args.phone:
            parser.error("--phone is required with --sms-record-url")
        if not args.sms_record_url:
            parser.error("--sms-record-url is required when --sms-provider=sms-record")
        sms_provider = SmsRecordOtpProvider(
            args.phone,
            args.sms_record_url,
            wait_seconds=args.sms_record_wait,
            poll_interval=args.sms_record_poll,
        )
    elif normalized_sms_provider == "hero_sms_rent":
        if not args.phone:
            parser.error("--phone is required when --sms-provider=hero-sms-rent")
        sms_provider = _build_hero_sms_rent_provider(
            phone_number=args.phone,
            api_key=args.sms_api_key,
            base_url=args.sms_base_url,
            country=args.sms_country,
            paypal_country=args.country,
            wait_seconds=args.sms_number_wait,
            poll_interval_seconds=args.sms_record_poll,
        )
    elif normalized_sms_provider in {"hero_sms", "smsbower"}:
        sms_provider = _build_sms_activate_provider(
            provider=normalized_sms_provider,
            api_key=args.sms_api_key or (args.smsbower_api_key if normalized_sms_provider == "smsbower" else None),
            base_url=args.sms_base_url,
            service=args.sms_service,
            country=args.sms_country,
            paypal_country=args.country,
            wait_seconds=args.sms_number_wait,
            poll_interval_seconds=args.sms_record_poll,
            min_price=args.sms_min_price,
            max_price=args.sms_max_price,
            preferred_price=args.sms_preferred_price,
        )
    else:
        sms_provider_requested = bool(args.smsbower or args.smsbower_api_key or _smsbower_enabled())
        sms_provider = _build_smsbower_provider(
            enabled=sms_provider_requested,
            api_key=args.smsbower_api_key,
        )
    if not args.phone and sms_provider is None:
        parser.error("--phone is required unless --smsbower, --sms-record-url, or SMSBOWER_ENABLED=1 is set")

    country = str(args.country or "BR").upper()
    default_phones = {
        "US": "+12025550123",
        "GB": "+447700900123",
        "NL": "+31612345678",
        "BR": "+5500000000000",
        "AU": "+61412345678",
        "CA": "+14370000000",
        "ID": "+6281234567890",
        "JP": "+819012345678",
        "MX": "+525512345678",
        "PH": "+639171234567",
        "TH": "+66812345678",
    }
    default_phone = default_phones.get(country, "+5500000000000")
    user = generate_user(args.phone or default_phone, country=country)
    card = generate_card(proxy_url=proxy_config.url, country=country)
    address = generate_address(proxy_url=proxy_config.url, country=country)

    logger.info(f"User: {user.first_name} {user.last_name}")
    logger.info("Email: {}", sanitize_for_log({"email": user.email})["email"])
    if sms_provider is None:
        logger.info("Phone: {}", sanitize_for_log({"phone": user.phone})["phone"])
    else:
        logger.info("Phone: OTP provider mode will supply/confirm the PayPal SMS")
    logger.info("CPF: <redacted>")
    logger.info("DOB: <redacted>")
    logger.info(
        "Card: {} exp={} cvv=<redacted>",
        sanitize_for_log({"cardNumber": card.number})["cardNumber"],
        card.expiry,
    )
    logger.info("Address generated: {}, {}-{}", address.district, address.city, address.state)
    logger.info(f"Proxy: {proxy_config.label}")

    flow = PayPalFlow(
        ba_token=args.ba_token,
        user=user,
        card=card,
        address=address,
        max_card_attempts=args.max_card_attempts,
        max_flow_attempts=args.max_flow_attempts,
        max_authorize_attempts=args.max_authorize_attempts,
        card_retry_delay_seconds=args.card_retry_delay,
        card_retry_jitter_seconds=args.card_retry_jitter,
        proxy_config=proxy_config,
        fingerprint_source=args.fingerprint_source,
        datadome_mode=args.datadome_mode,
        mtr_runtime=args.mtr_runtime,
        risk_signals_mode=args.risk_signals_mode,
        sms_provider=sms_provider,
    )

    try:
        result = flow.run()
    finally:
        close_global_traffic_recorder()

    if args.compare_roxy_capture and traffic_recorder is not None:
        try:
            from tools.compare_paypal_traffic import compare, write_markdown

            report = compare(
                traffic_recorder.root,
                Path(args.compare_roxy_capture).expanduser().resolve(),
            )
            report_path = traffic_recorder.root / "traffic_diff_report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            write_markdown(report, report_path.with_suffix(".md"))
            logger.info("Traffic diff report saved: {}", report_path)
            if report.get("findings"):
                logger.warning(
                    "Traffic diff findings: {}",
                    json.dumps(report.get("findings"), ensure_ascii=False, indent=2),
                )
        except Exception as exc:
            logger.warning("Traffic diff failed: {}", exc)

    print("\n" + "=" * 60)
    print("RESULT:")
    print(json.dumps(sanitize_for_log(result), indent=2, ensure_ascii=False))
    print("=" * 60)

    if result.get("status") == "success":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
