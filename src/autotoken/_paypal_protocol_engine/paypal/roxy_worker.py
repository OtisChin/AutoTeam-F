from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast


def _read_payload(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PayPal Roxy signup-context risk in an isolated process")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        payload = _read_payload(args.input)
        project_root = str(payload.get("project_root") or "").strip()
        if project_root and project_root not in sys.path:
            sys.path.insert(0, project_root)

        from paypal.roxy_fingerprint import (
            capture_roxy_runtime_profile,
            close_roxy_browser,
            roxy_browser_matches_proxy,
            run_phase1_risk_with_roxy_browser,
        )

        page_url = str(payload.get("page_url") or "")
        if not page_url:
            raise RuntimeError("page_url missing")
        proxy_url = str(payload.get("proxy_url") or "")
        roxy_browser = payload.get("roxy_browser") if isinstance(payload.get("roxy_browser"), dict) else {}
        runtime: dict[str, Any] = {}
        if not (isinstance(roxy_browser, dict) and roxy_browser.get("cdp_info") and roxy_browser_matches_proxy(roxy_browser, proxy_url)):
            if isinstance(roxy_browser, dict) and roxy_browser.get("cdp_info"):
                try:
                    close_roxy_browser(roxy_browser, delete=False)
                except Exception:
                    pass
            runtime = cast(dict[str, Any], capture_roxy_runtime_profile(keep_browser=True, proxy_url=proxy_url))
            roxy_browser = runtime.get("roxy_browser") if isinstance(runtime.get("roxy_browser"), dict) else {}
        if not isinstance(roxy_browser, dict) or not roxy_browser.get("cdp_info"):
            raise RuntimeError("Roxy browser cdp_info missing")

        result = run_phase1_risk_with_roxy_browser(
            cast(dict[str, Any], roxy_browser),
            page_url,
            cookies=cast(list[dict[str, Any]] | None, payload.get("cookies") if isinstance(payload.get("cookies"), list) else None),
            wait_seconds=float(payload.get("wait_seconds") or 18.0),
            app_id=str(payload.get("app_id") or "CHECKOUTUINODEWEB_ONBOARDING_LITE"),
            correlation_id=str(payload.get("correlation_id") or ""),
            document_html=str(payload.get("document_html") or ""),
            document_status=int(payload.get("document_status") or 200),
        )
        _write_json(args.output, {"ok": True, "result": result, "runtime": runtime, "roxy_browser": roxy_browser})
        return 0
    except Exception as exc:
        _write_json(args.output, {"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
