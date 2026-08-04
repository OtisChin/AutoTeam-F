"""CLI for the standalone OAuth relogin package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .oauth_relogin import (
    JsonPhonePoolProvider,
    OAuthConfig,
    build_phone_sms_config_report,
    create_sms_provider,
    load_phone_sms_provider_configs,
    run_browser_oauth_relogin_flow,
)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_json_file(path: str) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m standalone.oauth_relogin")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Print safe phone/SMS provider configuration report")

    import_phones = sub.add_parser("import-phones", help="Import phone_pool numbers into JSON")
    import_phones.add_argument("--phone-pool", default="data/oauth-phone-pool.json")
    import_phones.add_argument("--text", required=True, help="Lines like '+12025550111----https://sms.example/inbox'")

    login = sub.add_parser("login", help="Run browser-helper OAuth relogin and write JSON auth bundle")
    login.add_argument("--email", required=True)
    login.add_argument("--password", default="")
    login.add_argument("--output-dir", default="oauth-output")
    login.add_argument("--provider", default="")
    login.add_argument("--phone-pool", default="data/oauth-phone-pool.json")
    login.add_argument("--phone-code", default="", help="Manual phone OTP; omit to poll provider adapter")
    login.add_argument("--proxy-url", default="")
    login.add_argument("--oauth-config-json", default="", help="Optional OAuthConfig JSON file")
    login.add_argument("--no-phone", action="store_true", help="Do not bind phone during browser relogin")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config":
        _print_json(build_phone_sms_config_report(load_phone_sms_provider_configs()))
        return 0

    if args.command == "import-phones":
        provider = JsonPhonePoolProvider(args.phone_pool)
        _print_json(provider.import_phones(args.text))
        return 0

    if args.command == "login":
        config_data = _load_json_file(args.oauth_config_json)
        config = OAuthConfig(**config_data) if config_data else OAuthConfig.from_env()
        sms_provider = None
        if not args.no_phone:
            sms_provider = create_sms_provider(
                args.provider or None,
                configs=load_phone_sms_provider_configs(),
                phone_pool_path=args.phone_pool,
            )
        result = run_browser_oauth_relogin_flow(
            email=args.email,
            password=args.password,
            output_dir=args.output_dir,
            config=config,
            sms_provider=sms_provider,
            phone_code_provider=(lambda _phone: args.phone_code) if args.phone_code else None,
            proxy_url=args.proxy_url or None,
        )
        _print_json(result)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
