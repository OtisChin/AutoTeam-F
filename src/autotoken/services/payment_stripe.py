"""Shared Stripe/checkout constants and pure helpers for payment flows."""

from __future__ import annotations

import os
import re

DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRacViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "922d612e68"
STRIPE_API = "https://api.stripe.com"
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"


def extract_checkout_session_id(checkout_url: str = "", raw: dict | None = None) -> str:
    data = raw if isinstance(raw, dict) else {}
    for key in ("checkout_session_id", "session_id", "id"):
        value = str(data.get(key) or "").strip()
        if value.startswith("cs_"):
            return value
    matched = re.search(r"(cs_[A-Za-z0-9_]+)", str(checkout_url or ""))
    return matched.group(1) if matched else ""


def stripe_runtime_from_env() -> dict:
    return {
        "version": os.environ.get("GOPAY_STRIPE_RUNTIME_VERSION", DEFAULT_STRIPE_RUNTIME_VERSION).strip(),
        "js_checksum": os.environ.get("GOPAY_STRIPE_JS_CHECKSUM", "").strip(),
        "rv_timestamp": os.environ.get("GOPAY_STRIPE_RV_TIMESTAMP", "").strip(),
    }
