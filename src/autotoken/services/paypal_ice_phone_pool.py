"""PayPal ICE phone number pool — SMS phone + API URL pairs for job creation."""

from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any

from autotoken.storage import sqlite_store

NAMESPACE = "paypal_ice_phone_pool"
KEY = "items"
MAX_CONCURRENCY = 100
_LOCK = threading.RLock()
_IN_USE: dict[str, str] = {}  # phone_id -> job_id running on it
_PHONE_TO_JOB: dict[str, str] = {}  # phone_id -> job_id
_JOB_TO_PHONE: dict[str, str] = {}  # job_id -> phone_id


def _now() -> float:
    return time.time()


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item or {})
    phone = str(data.get("phone_number") or "").strip()
    sms_api = str(data.get("sms_api") or data.get("sms_url") or "").strip()
    status = str(data.get("status") or "available").strip().lower()
    if status not in {"available", "in_use", "disabled", "error"}:
        status = "available"
    return {
        "id": str(data.get("id") or uuid.uuid4().hex),
        "phone_number": phone,
        "sms_api": sms_api,
        "status": status,
        "note": str(data.get("note") or "").strip(),
        "error_message": str(data.get("error_message") or "").strip(),
        "last_used_at": data.get("last_used_at"),
        "created_at": float(data.get("created_at") or _now()),
        "updated_at": float(data.get("updated_at") or _now()),
    }


def _raw_items() -> list[dict[str, Any]]:
    data = sqlite_store.get_json(NAMESPACE, KEY, default=[])
    if not isinstance(data, list):
        return []
    return [_normalize_item(item) for item in data if isinstance(item, dict)]


def _save_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_item(item) for item in items if isinstance(item, dict)]
    sqlite_store.set_json(NAMESPACE, KEY, normalized)
    return normalized


def _with_runtime_status(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    phone_id = data["id"]
    if phone_id in _IN_USE:
        data["status"] = "in_use"
        data["current_job_id"] = _IN_USE[phone_id]
    else:
        data["current_job_id"] = None
    return data


def list_phones() -> list[dict[str, Any]]:
    with _LOCK:
        return [_with_runtime_status(item) for item in _raw_items()]


def add_phone(payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_item(payload)
    if not item["phone_number"]:
        raise ValueError("手机号不能为空")
    if not item["sms_api"]:
        raise ValueError("接码 API 不能为空")
    with _LOCK:
        items = _raw_items()
        phone_key = re.sub(r"\D+", "", item["phone_number"])
        for existing in items:
            existing_key = re.sub(r"\D+", "", existing.get("phone_number") or "")
            if existing_key == phone_key and existing_key:
                raise ValueError(f"手机号 {item['phone_number']} 已存在")
        item["created_at"] = _now()
        item["updated_at"] = _now()
        items.insert(0, item)
        _save_items(items)
        return _with_runtime_status(item)


def update_phone(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    target = str(item_id or "").strip()
    if not target:
        raise ValueError("ID 不能为空")
    with _LOCK:
        items = _raw_items()
        for index, existing in enumerate(items):
            if existing["id"] != target:
                continue
            merged = dict(existing)
            merged.update(dict(payload or {}))
            merged["id"] = target
            merged["updated_at"] = _now()
            item = _normalize_item(merged)
            if not item["phone_number"]:
                raise ValueError("手机号不能为空")
            if not item["sms_api"]:
                raise ValueError("接码 API 不能为空")
            items[index] = item
            _save_items(items)
            return _with_runtime_status(item)
    raise KeyError("手机号不存在")


def delete_phones(ids: list[str]) -> int:
    targets = {str(item or "").strip() for item in ids or [] if str(item or "").strip()}
    if not targets:
        return 0
    with _LOCK:
        items = _raw_items()
        for tid in targets:
            _IN_USE.pop(tid, None)
            job_id = _PHONE_TO_JOB.pop(tid, None)
            if job_id:
                _JOB_TO_PHONE.pop(job_id, None)
        kept = [item for item in items if item["id"] not in targets]
        deleted = len(items) - len(kept)
        if deleted:
            _save_items(kept)
        return deleted


def import_phones(text: str) -> dict[str, Any]:
    """Import phone | sms_api lines."""
    entries: list[dict[str, str]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "----" in line:
            parts = re.split(r"\s*-{4,}\s*", line, maxsplit=1)
        elif "|" in line:
            parts = re.split(r"\s*\|\s*", line, maxsplit=1)
        elif "\t" in line:
            parts = line.split("\t", 1)
        else:
            match = re.match(r"^(\S+)\s+-\s+(https?://.+)$", line, re.I)
            if not match:
                match = re.match(r"^(\S+)\s+(https?://.+)$", line, re.I)
            if match:
                parts = [match.group(1), match.group(2)]
            else:
                continue
        if len(parts) != 2:
            continue
        phone, sms_api = parts[0].strip(), parts[1].strip()
        if not phone or not sms_api or not sms_api.startswith(("http://", "https://")):
            continue
        entries.append({"phone_number": phone, "sms_api": sms_api})

    if not entries:
        raise ValueError("未能解析到有效的手机号----接码API 格式")

    with _LOCK:
        items = _raw_items()
        known_keys = {re.sub(r"\D+", "", item.get("phone_number") or "") for item in items}
        added = 0
        skipped = 0
        for entry in entries:
            pk = re.sub(r"\D+", "", entry["phone_number"])
            if pk in known_keys:
                skipped += 1
                continue
            known_keys.add(pk)
            item = _normalize_item(entry)
            item["created_at"] = _now()
            item["updated_at"] = _now()
            items.insert(0, item)
            added += 1
        if added:
            _save_items(items)
        return {
            "added": added,
            "skipped": skipped,
            "total": len(items),
            "items": [_with_runtime_status(item) for item in items],
        }


def acquire_phone() -> dict[str, Any] | None:
    """Acquire an available phone for use. Returns None if none available."""
    with _LOCK:
        items = _raw_items()
        now = _now()
        for item in items:
            phone_id = item["id"]
            if phone_id in _IN_USE:
                continue
            if item["status"] in ("disabled", "error"):
                continue
            # Mark as in-use
            _IN_USE[phone_id] = "pending"
            item["last_used_at"] = now
            _save_items(items)
            return _with_runtime_status(item)
    return None


def release_phone(phone_id: str) -> dict[str, Any] | None:
    """Release a phone back to the pool."""
    target = str(phone_id or "").strip()
    if not target:
        return None
    with _LOCK:
        _IN_USE.pop(target, None)
        job_id = _PHONE_TO_JOB.pop(target, None)
        if job_id:
            _JOB_TO_PHONE.pop(job_id, None)
        items = _raw_items()
        for item in items:
            if item["id"] == target:
                if item["status"] == "error":
                    pass
                item["updated_at"] = _now()
                _save_items(items)
                return _with_runtime_status(item)
    return None


def associate_job(phone_id: str, job_id: str) -> None:
    """Link a phone to an active ICE job."""
    with _LOCK:
        if phone_id in _IN_USE:
            _IN_USE[phone_id] = job_id
        _PHONE_TO_JOB[phone_id] = job_id
        _JOB_TO_PHONE[job_id] = phone_id


def phone_for_job(job_id: str) -> str | None:
    """Get phone_id for a running job."""
    return _JOB_TO_PHONE.get(job_id)


def available_count() -> int:
    """Number of phones currently available."""
    with _LOCK:
        items = _raw_items()
        count = 0
        for item in items:
            if item["id"] not in _IN_USE and item["status"] not in ("disabled", "error"):
                count += 1
        return count


def active_phone_count() -> int:
    """Number of phones currently in use."""
    return len(_IN_USE)


def pool_stats() -> dict[str, Any]:
    """Return pool statistics."""
    with _LOCK:
        items = _raw_items()
        total = len(items)
        available = 0
        in_use = 0
        disabled = 0
        error = 0
        for item in items:
            if item["id"] in _IN_USE:
                in_use += 1
            elif item["status"] == "disabled":
                disabled += 1
            elif item["status"] == "error":
                error += 1
            else:
                available += 1
        return {
            "total": total,
            "available": available,
            "in_use": in_use,
            "disabled": disabled,
            "error": error,
            "max_concurrency": min(total if total > 0 else 0, MAX_CONCURRENCY),
            "active_concurrency": in_use,
        }
