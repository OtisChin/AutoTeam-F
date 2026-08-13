from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autotoken.api_routes.momo_vn import _load_token_for_email  # noqa: E402
from autotoken.payments.momo_vn import MomoVnJobConfig, detect_momo_eligibility, generate_momo_vn_trial  # noqa: E402


DEFAULT_EMAILS = [
    "vitriol.debased-6v@icloud.com",
    "loyalty-dance.3r@icloud.com",
    "95cavers_dusters@icloud.com",
]


def _redact(value: Any, keep: int = 10) -> str:
    text = str(value or "")
    if len(text) <= keep:
        return text
    return f"{text[:keep]}..."


def _parse_proxies(raw: str) -> list[str]:
    lines = [line.strip() for line in str(raw or "").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MoMo VN checkout/OAICS eligibility using saved auth_session tokens.")
    parser.add_argument("emails", nargs="*", default=DEFAULT_EMAILS)
    parser.add_argument("--proxies-file", default="", help="File containing one proxy per line.")
    parser.add_argument("--proxy", action="append", default=[], help="Proxy entry. Can be repeated.")
    parser.add_argument("--local-proxy", default="")
    parser.add_argument("--kookeey-user", default="")
    parser.add_argument("--kookeey-pass", default="")
    parser.add_argument("--kookeey-endpoint", default="gate.kookeey.info:1000")
    parser.add_argument("--extract", action="store_true", help="After eligibility succeeds, actually run MoMo link extraction.")
    parser.add_argument("--front-promo", action="store_true", help="Create checkout with promo_campaign instead of applying promo after oaics checkout.")
    args = parser.parse_args()

    proxies = list(args.proxy or [])
    if args.proxies_file:
        proxies.extend(_parse_proxies(Path(args.proxies_file).read_text(encoding="utf-8")))

    if not proxies and not (args.kookeey_user and args.kookeey_pass):
        print("缺少代理：请提供 --proxy / --proxies-file 或 --kookeey-user + --kookeey-pass", file=sys.stderr)
        return 2

    exit_code = 0
    for email in args.emails:
        print(f"\n=== {email} ===")
        token = _load_token_for_email(email)
        if not token:
            _print_json({"email": email, "ok": False, "error": "本地未找到可用 access token/auth_session"})
            exit_code = 1
            continue
        logs: list[str] = []

        def log(message: str) -> None:
            logs.append(message)
            print(message)

        cfg = MomoVnJobConfig(
            access_token=token,
            local_proxy=args.local_proxy,
            kookeey_user=args.kookeey_user,
            kookeey_pass=args.kookeey_pass,
            kookeey_endpoint=args.kookeey_endpoint,
            direct_proxies=proxies,
            front_promo=args.front_promo,
        )
        try:
            eligibility = detect_momo_eligibility(cfg, log)
            summary = {
                "email": email,
                "ok": True,
                "mode": "extract" if args.extract else "probe",
                "checkout_flow": eligibility.get("checkout_flow") or ("oaics" if str(eligibility.get("cs_id") or "").startswith("oaics_") else "cs"),
                "cs_id_prefix": _redact(eligibility.get("cs_id")),
                "processor": eligibility.get("processor"),
                "status": eligibility.get("status"),
                "has_momo": eligibility.get("has_momo"),
                "amount": eligibility.get("amount"),
                "currency": eligibility.get("currency"),
                "payment_method_types": eligibility.get("payment_method_types"),
                "ordered_payment_method_types": eligibility.get("ordered_payment_method_types"),
                "custom_payment_methods": [
                    {"id": item.get("id"), "display_name": item.get("display_name") or item.get("name") or item.get("type")}
                    for item in eligibility.get("custom_payment_methods", [])
                    if isinstance(item, dict)
                ],
            }
            _print_json(summary)
            if args.extract and eligibility.get("has_momo") and str(eligibility.get("status") or "").lower() == "eligible":
                result = generate_momo_vn_trial(MomoVnJobConfig(**{**cfg.__dict__, "preflight_result": eligibility}), log)
                fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
                _print_json(
                    {
                        "email": email,
                        "ok": True,
                        "extracted": True,
                        "momo_link": fields.get("momo_link"),
                        "provider_redirect_url": fields.get("provider_redirect_url"),
                        "stripe_redirect_url": fields.get("stripe_redirect_url"),
                        "cs_id_prefix": _redact(fields.get("cs_id") or eligibility.get("cs_id")),
                        "link_source": fields.get("link_source"),
                        "link_binding": fields.get("link_binding"),
                    }
                )
        except Exception as exc:
            _print_json({"email": email, "ok": False, "error": str(exc)})
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
