r"""Test PayPal JP no-card link extraction across proxy combinations with edu.rexoox.com accounts.

Usage (dry-run, check prereqs only):
  .venv\Scripts\python.exe scripts\test_paypal_jp_extract_link.py --check

Usage (live extraction):
  .venv\Scripts\python.exe scripts\test_paypal_jp_extract_link.py --live --accounts 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _load_env() -> None:
    for path in (ROOT / ".env", ROOT / "data" / ".env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('\"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


PROXIES: dict[str, str] = {
    "US": "socks5://hyrj1177789-region-US-st-California-city-Los%20Angeles-sid-zcCXc21Z-t-60:smhwqe9f@us.arxlabs.io:3010",
    "JP": "socks5://hyrj1177789-region-JP-st-Kyoto-city-Kyoto-sid-xyVvptmk-t-60:smhwqe9f@us.arxlabs.io:3010",
    "AU": "socks5://hyrj1177789-region-AU-st-Queensland-city-Ingham-sid-URQ2xZmy-t-60:smhwqe9f@us.arxlabs.io:3010",
}

COMBINATIONS: list[tuple[str, str | None, str]] = [
    (PROXIES["JP"], None, "JP-only"),
    (PROXIES["JP"], PROXIES["US"], "JP+US"),
    (PROXIES["US"], None, "US-only"),
    (PROXIES["AU"], None, "AU-only"),
    (PROXIES["JP"], PROXIES["AU"], "JP+AU"),
]

AUTH_SESSION_DIR = ROOT / "data" / "auth_session"


def mask_proxy_url(proxy_url: str | None) -> str:
    value = str(proxy_url or "").strip()
    if not value:
        return "(same)"
    if "@" not in value:
        return value[:80]
    scheme_and_auth, host = value.rsplit("@", 1)
    scheme = scheme_and_auth.split("://", 1)[0] if "://" in scheme_and_auth else "proxy"
    return f"{scheme}://***@{host[:60]}"


def list_edu_accounts() -> list[tuple[str, Path]]:
    results: list[tuple[str, Path]] = []
    for f in sorted(AUTH_SESSION_DIR.glob("*.json")):
        name = f.stem
        if "@" not in name:
            continue
        local, domain = name.split("@", 1)
        email = f"{local}@{domain.replace('_', '.')}"
        results.append((email, f))
    return results


def load_access_token(auth_file: Path) -> str:
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    return str(data.get("accessToken") or "").strip()


def load_auth_context(auth_file: Path) -> dict[str, str]:
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    return {
        "access_token": str(
            data.get("access_token") or data.get("accessToken") or data.get("chatgpt_access_token") or ""
        ).strip(),
        "session_token": str(data.get("session_token") or data.get("sessionToken") or "").strip(),
        "cookie_header": str(data.get("cookie_header") or "").strip(),
        "account_id": str(data.get("account_id") or data.get("accountId") or "").strip(),
        "device_id": str(data.get("device_id") or data.get("oai_device_id") or "").strip(),
        "user_agent": str(data.get("user_agent") or "").strip(),
        "openai_sentinel_token": str(data.get("openai_sentinel_token") or "").strip(),
        "oai_client_version": str(data.get("oai_client_version") or "").strip(),
        "oai_client_build_number": str(data.get("oai_client_build_number") or "").strip(),
    }


def check_token_valid(token: str) -> bool:
    if not token or len(token) < 50:
        return False
    try:
        parts = token.split(".")
        if len(parts) < 3:
            return False
        import base64
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp = int(decoded.get("exp", 0))
        return exp > time.time() + 300
    except Exception:
        return False


def test_extraction(
    proxy_url: str,
    provider_proxy_url: str | None,
    email: str,
    auth_context: dict[str, str],
    paypal_ba_mode: str,
    payment_method_country: str,
    timeout: int = 120,
) -> dict[str, Any]:
    from autotoken.payments.paypal_bind_executor import _paypal_extract_ba_link

    provider = str(provider_proxy_url or proxy_url)
    progress_msgs: list[dict[str, Any]] = []

    def on_progress(event: dict[str, Any]) -> None:
        progress_msgs.append(event)

    start = time.monotonic()
    try:
        result = _paypal_extract_ba_link(
            access_token=str(auth_context.get("access_token") or ""),
            session_token=str(auth_context.get("session_token") or ""),
            account_id=str(auth_context.get("account_id") or ""),
            device_id=str(auth_context.get("device_id") or ""),
            cookie_header=str(auth_context.get("cookie_header") or ""),
            user_agent=str(auth_context.get("user_agent") or ""),
            openai_sentinel_token=str(auth_context.get("openai_sentinel_token") or ""),
            oai_client_version=str(auth_context.get("oai_client_version") or ""),
            oai_client_build_number=str(auth_context.get("oai_client_build_number") or ""),
            proxy_url=proxy_url,
            provider_proxy_url=provider,
            approve_proxy_url=provider,
            payment_method_country=payment_method_country,
            paypal_ba_mode=paypal_ba_mode,
            timeout_seconds=timeout,
            is_cancelled=lambda: False,
            on_progress=on_progress,
        )
        elapsed = round(time.monotonic() - start, 1)
        return {
            "email": email,
            "elapsed_s": elapsed,
            "result": result,
            "progress": progress_msgs,
        }
    except Exception as exc:
        elapsed = round(time.monotonic() - start, 1)
        return {
            "email": email,
            "elapsed_s": elapsed,
            "result": {"status": "exception", "message": str(exc), "type": type(exc).__name__},
            "progress": progress_msgs,
        }


def ensure_pplink_exists() -> Path:
    candidates = [
        ROOT / "vendor" / "pplink" / "pplink.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise SystemExit("pplink.exe not found in vendor/pplink/")


def run_checks(args: argparse.Namespace) -> int:
    accounts = list_edu_accounts()
    print(f"Found {len(accounts)} edu.rexoox.com accounts\n")
    valid = 0
    expired = 0
    missing = 0
    for email, auth_file in accounts:
        token = load_access_token(auth_file)
        if not token:
            print(f"  MISSING_TOKEN {email}")
            missing += 1
        elif not check_token_valid(token):
            print(f"  EXPIRED {email}")
            expired += 1
        else:
            print(f"  VALID   {email}")
            valid += 1
    print(f"\nSummary: {valid} valid, {expired} expired, {missing} missing_token")
    return 0 if valid > 0 else 1


def run_live(args: argparse.Namespace) -> int:
    ensure_pplink_exists()
    accounts = list_edu_accounts()

    valid_accounts: list[tuple[str, Path, str]] = []
    wanted_emails = {
        item.strip().lower()
        for raw in (getattr(args, "email", None) or [])
        for item in str(raw or "").split(",")
        if item.strip()
    }
    for email, auth_file in accounts:
        if wanted_emails and email.lower() not in wanted_emails:
            continue
        token = load_access_token(auth_file)
        if token and check_token_valid(token):
            valid_accounts.append((email, auth_file, token))

    if not valid_accounts:
        print("No accounts with valid tokens available.")
        return 1

    selected_combo = str(getattr(args, "combo", "") or "").strip()
    combinations = [
        combo for combo in COMBINATIONS if not selected_combo or combo[2].lower() == selected_combo.lower()
    ]
    if not combinations:
        available = ", ".join(label for *_rest, label in COMBINATIONS)
        print(f"No matching proxy combination: {selected_combo}. Available: {available}")
        return 1

    max_accounts = args.accounts or 3
    start_index = max(0, int(getattr(args, "start_index", 0) or 0))
    accounts_to_use = valid_accounts[start_index : start_index + max_accounts]
    if not accounts_to_use:
        print(f"No valid accounts available from start index {start_index}.")
        return 1
    print(f"Testing {len(accounts_to_use)} accounts x {len(combinations)} proxy combinations")
    print(f"Accounts: {', '.join(a[0] for a in accounts_to_use)}\n")

    results: list[dict[str, Any]] = []

    for proxy_url, provider_url, label in combinations:
        print(f"\n{'='*60}")
        print(f"Combination: {label}")
        print(f"  proxy_url:          {mask_proxy_url(proxy_url)}")
        print(f"  provider_proxy_url: {mask_proxy_url(provider_url)}")
        print(f"{'='*60}")

        combo_success = 0
        combo_fail = 0

        for email, auth_file, _token in accounts_to_use:
            print(f"\n  Testing {email}...")
            outcome = test_extraction(
                proxy_url=proxy_url,
                provider_proxy_url=provider_url,
                email=email,
                auth_context=load_auth_context(auth_file),
                paypal_ba_mode=str(args.paypal_ba_mode or "us"),
                payment_method_country=str(args.payment_country or "US").strip().upper(),
                timeout=args.timeout or 120,
            )
            status = outcome["result"].get("status", "unknown")
            elapsed = outcome["elapsed_s"]
            ba_token = outcome["result"].get("ba_token", "") or outcome["result"].get("approve_url", "")
            message = outcome["result"].get("message", "")

            if status == "success":
                combo_success += 1
                print(f"    SUCCESS ({elapsed}s)")
                if ba_token:
                    print(f"    BA token: {str(ba_token)[:80]}...")
            else:
                combo_fail += 1
                failure_stage = outcome["result"].get("failure_stage", "")
                print(f"    FAILED  ({elapsed}s) stage={failure_stage}")
                if message:
                    print(f"    {message[:200]}")

            outcome["proxy_combo"] = label
            results.append(outcome)

        print(f"\n  {label} summary: {combo_success} success, {combo_fail} failed")

    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    by_combo: dict[str, dict[str, int]] = {}
    for r in results:
        combo = r["proxy_combo"]
        if combo not in by_combo:
            by_combo[combo] = {"success": 0, "failed": 0}
        status = r["result"].get("status", "")
        if status == "success":
            by_combo[combo]["success"] += 1
        else:
            by_combo[combo]["failed"] += 1

    for combo, counts in by_combo.items():
        total = counts["success"] + counts["failed"]
        pct = round(counts["success"] / total * 100) if total else 0
        print(f"  {combo}: {counts['success']}/{total} success ({pct}%)")

    out_path = ROOT / "outputs" / "paypal_jp_extract_test.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nDetailed results saved to: {out_path}")

    return 0 if any(c["success"] > 0 for c in by_combo.values()) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Test PayPal JP no-card link extraction")
    p.add_argument("--check", action="store_true", help="Check token validity only (no live actions)")
    p.add_argument("--live", action="store_true", help="Run live extraction tests")
    p.add_argument("--accounts", type=int, default=3, help="Max accounts per proxy combination (default: 3)")
    p.add_argument("--start-index", type=int, default=0, help="Start offset in the valid account list (default: 0)")
    p.add_argument("--email", action="append", help="Only test the selected email(s); repeat or comma-separate")
    p.add_argument("--timeout", type=int, default=120, help="Timeout per extraction attempt (default: 120s)")
    p.add_argument("--paypal-ba-mode", choices=["us", "eu", "br"], default="us", help="BA extraction mode")
    p.add_argument("--payment-country", choices=["US", "AU", "BR"], default="US", help="PayPal payment/billing country")
    p.add_argument(
        "--combo",
        choices=[label for *_rest, label in COMBINATIONS],
        help="Only run one proxy combination, e.g. JP+US or JP+AU",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check:
        return run_checks(args)
    if args.live:
        return run_live(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
