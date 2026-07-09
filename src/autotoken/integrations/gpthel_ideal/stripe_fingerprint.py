"""Stripe.js v3 anti-bot fingerprint reuse helper.

Background
----------
Stripe `/v1/payment_pages/{cs}/confirm` requires these anti-bot fields:
  - js_checksum   (token minted by m.stripe.com/6, NOT computed locally)
  - rv_timestamp  (PerformanceObserver entries encoded via shared.js module 41069)
  - version       (stripe.js bundle SHA[:10])
  - _stripe_version (api version + beta flags)

Empirical finding (2026-06-17, _replay_test.py):
  Captured `js_checksum + rv_timestamp + version + _stripe_version` from a real
  browser confirm can be REPLAYED across brand-new cs/pm without rejection.
  Stripe does NOT enforce cs/timestamp binding on these fields server-side
  (at least for the OpenAI merchant + PayPal/GoPay flow).

So instead of implementing the full m.stripe.com/6 device-fingerprint protocol,
we just keep a captured tuple per link_type and patch it into every Python-side
confirm body.

Capture refresh
---------------
When stripe rotates server-side rules and a tuple stops working, the only step
is to re-capture a fresh confirm body via the BitBrowser path and drop it into
`data/` (preferred) or legacy `run-logs/`. This module auto-picks the matching
sample by link_type.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse as up
from pathlib import Path
from typing import Any

__all__ = [
    "FingerprintNotFound",
    "load_capture",
    "extract_fingerprint",
    "apply_fingerprint",
    "fingerprint_for_link_type",
]


class FingerprintNotFound(Exception):
    pass


_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data"
_LEGACY_LOG_DIR = _ROOT.parent / "run-logs"

# Mapping link_type -> ordered list of capture filenames to try.
# Later entries are fallbacks if the earlier captures are missing or stale.
_CAPTURE_FILES: dict[str, tuple[str, ...]] = {
    "gopay":  ("confirm_body.txt",),
    "paypal": ("paypal_confirm_post.txt",
               "paypal_fresh_confirm_post_2.txt",
               "paypal_sweep_confirm_post.txt"),
    "hosted": ("paypal_confirm_post.txt",),
}

# Field names whose VALUES we reuse from the historic capture verbatim.
# Everything else in the confirm body uses fresh per-request values.
REUSE_KEYS: tuple[str, ...] = (
    "js_checksum",
    "rv_timestamp",
    "version",
    "_stripe_version",
)


def _resolve_capture_path(link_type: str) -> Path:
    candidates = _CAPTURE_FILES.get(link_type, _CAPTURE_FILES["paypal"])
    for name in candidates:
        for parent in (_DATA_DIR, _LEGACY_LOG_DIR):
            p = parent / name
            if p.is_file() and p.stat().st_size > 0:
                return p
    raise FingerprintNotFound(
        f"no capture file found for link_type={link_type!r}; "
        f"tried {candidates} under {_DATA_DIR} and {_LEGACY_LOG_DIR}"
    )


def load_capture(link_type: str = "paypal", path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Parse a historic stripe confirm POST body into a {field: value} dict.

    `link_type` selects a default capture file; pass `path` to override.
    """
    if path:
        p = Path(path)
    else:
        p = _resolve_capture_path(link_type)
    body = p.read_text(encoding="utf-8")
    return dict(up.parse_qsl(body, keep_blank_values=True))


def extract_fingerprint(capture: dict[str, str]) -> dict[str, str]:
    """Pick only the anti-bot fields out of a parsed capture dict."""
    out: dict[str, str] = {}
    for k in REUSE_KEYS:
        v = capture.get(k)
        if v:
            out[k] = v
    missing = [k for k in REUSE_KEYS if k not in out]
    if missing:
        raise FingerprintNotFound(f"capture missing anti-bot keys: {missing}")
    return out


def apply_fingerprint(
    body: dict[str, str],
    link_type: str = "paypal",
    *,
    capture_path: str | os.PathLike[str] | None = None,
    overwrite: bool = True,
) -> dict[str, str]:
    """Patch js_checksum/rv_timestamp/version/_stripe_version into a confirm body.

    Mutates `body` in-place AND returns it. By default overwrites any existing
    values (caller's placeholders from app.py); set overwrite=False to only fill
    missing keys.
    """
    fp = extract_fingerprint(load_capture(link_type, capture_path))
    for k, v in fp.items():
        if overwrite or k not in body or not body[k]:
            body[k] = v
    return body


def fingerprint_for_link_type(link_type: str, capture_path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Convenience: just give me the {field: value} dict to merge in."""
    return extract_fingerprint(load_capture(link_type, capture_path))


def _cli(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        prog = Path(argv[0]).name
        print(f"usage: {prog} <link_type> [capture_path]")
        print(f"       {prog} dump <link_type>")
        return 0
    cmd = argv[1]
    if cmd == "dump":
        link_type = argv[2] if len(argv) > 2 else "paypal"
        fp = fingerprint_for_link_type(link_type)
        print(json.dumps(fp, ensure_ascii=False, indent=2))
        return 0
    link_type = cmd
    cap_path = argv[2] if len(argv) > 2 else None
    fp = fingerprint_for_link_type(link_type, cap_path)
    for k, v in fp.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
