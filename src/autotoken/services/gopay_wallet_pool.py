"""Reusable GoPay wallet pool helpers for bind task orchestration."""

import logging
import re
import threading
import time
from typing import Any

from autotoken.services import gopay_runtime

logger = logging.getLogger(__name__)

GOPAY_REUSABLE_WALLET_POOL_LOCK = threading.Lock()
GOPAY_REUSABLE_WALLET_POOL: list[dict[str, Any]] = []


def reusable_wallet_ttl_seconds() -> int:
    return max(60, int(gopay_runtime.env_float("GOPAY_AUTO_SIGNUP_WALLET_POOL_TTL_SECONDS", 20 * 60)))


def wallet_phone(wallet: Any) -> str:
    phone = str(getattr(wallet, "phone_number", "") or "").strip()
    if phone:
        return phone
    try:
        return str((wallet.as_phone_account() or {}).get("phone_number") or "").strip()
    except Exception:
        return ""


def wallet_bridge_token(wallet: Any) -> str:
    token = str(getattr(wallet, "bridge_token", "") or "").strip()
    if token:
        return token
    try:
        account = wallet.as_phone_account() or {}
    except Exception:
        account = {}
    raw = str(account.get("bridge_token") or account.get("bridgeToken") or "").strip()
    if raw:
        return raw
    sms_url = str(account.get("sms_url") or account.get("smsUrl") or "").strip()
    matched = re.search(r"/otp/gopay-signup/([^/?#]+)", sms_url)
    return matched.group(1) if matched else ""


def wallet_account(wallet: Any) -> dict[str, Any]:
    try:
        account = dict(wallet.as_phone_account() or {})
    except Exception:
        account = {}
    if "phone_number" not in account:
        account["phone_number"] = wallet_phone(wallet)
    if "bridge_token" not in account:
        bridge_token = wallet_bridge_token(wallet)
        if bridge_token:
            account["bridge_token"] = bridge_token
    return account


def prune_reusable_wallet_pool(now: float | None = None) -> None:
    current = time.time() if now is None else float(now)
    expired: list[dict[str, Any]] = []
    with GOPAY_REUSABLE_WALLET_POOL_LOCK:
        kept = []
        for entry in GOPAY_REUSABLE_WALLET_POOL:
            if float(entry.get("expires_at") or 0) <= current:
                expired.append(entry)
            else:
                kept.append(entry)
        GOPAY_REUSABLE_WALLET_POOL[:] = kept
    for entry in expired:
        wallet = entry.get("wallet")
        try:
            if wallet is not None:
                wallet.close(success=False)
        except Exception:
            logger.debug("[gopay-bind] close expired reusable GoPay wallet failed", exc_info=True)


def push_reusable_wallet(
    wallet: Any,
    *,
    task_id: str = "",
    run_id: str = "",
    created_at: float | None = None,
    funded: bool = False,
) -> dict[str, Any] | None:
    if wallet is None:
        return None
    account = wallet_account(wallet)
    phone = str(account.get("phone_number") or "").strip()
    if not phone:
        return None
    current = time.time()
    started_at = float(created_at or current)
    expires_at = started_at + reusable_wallet_ttl_seconds()
    if expires_at <= current:
        return None
    entry = {
        "wallet": wallet,
        "phone_number": phone,
        "country_code": gopay_runtime.normalized_pool_country(account.get("country_code") or "62"),
        "gopay_pin": str(account.get("gopay_pin") or "").strip(),
        "sms_url": str(account.get("sms_url") or "").strip(),
        "bridge_token": str(account.get("bridge_token") or "").strip(),
        "created_at": started_at,
        "expires_at": expires_at,
        "funded": bool(funded),
        "task_id": task_id,
        "run_id": run_id,
    }
    with GOPAY_REUSABLE_WALLET_POOL_LOCK:
        GOPAY_REUSABLE_WALLET_POOL[:] = [
            item
            for item in GOPAY_REUSABLE_WALLET_POOL
            if str(item.get("phone_number") or "") != phone and item.get("wallet") is not wallet
        ]
        GOPAY_REUSABLE_WALLET_POOL.append(entry)
    return entry


def pop_reusable_wallet(*, gopay_pin: str, country_code: str = "62") -> dict[str, Any] | None:
    prune_reusable_wallet_pool()
    pin = str(gopay_pin or "").strip()
    country = gopay_runtime.normalized_pool_country(country_code)
    with GOPAY_REUSABLE_WALLET_POOL_LOCK:
        for index, entry in enumerate(GOPAY_REUSABLE_WALLET_POOL):
            if pin and str(entry.get("gopay_pin") or "").strip() != pin:
                continue
            if gopay_runtime.normalized_pool_country(entry.get("country_code") or "62") != country:
                continue
            return GOPAY_REUSABLE_WALLET_POOL.pop(index)
    return None
