"""OAuth add-phone phone pool persistence and allocation."""

from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any

from autoteam import sqlite_store

MAX_BINDINGS_PER_PHONE = 3
NAMESPACE = "oauth_phone_pool"
KEY = "items"
_LOCK = threading.RLock()


def normalize_phone_key(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    return digits or str(phone or "").strip().lower()


def _now() -> float:
    return time.time()


def _raw_items() -> list[dict[str, Any]]:
    data = sqlite_store.get_json(NAMESPACE, KEY, default=[])
    if not isinstance(data, list):
        return []
    return [_normalize_item(item) for item in data if isinstance(item, dict)]


def _save_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_item(item) for item in items if isinstance(item, dict)]
    sqlite_store.set_json(NAMESPACE, KEY, normalized)
    return normalized


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item or {})
    created_at = data.get("created_at") or _now()
    bound_emails = data.get("bound_emails") if isinstance(data.get("bound_emails"), list) else []
    deduped_emails: list[str] = []
    seen_emails: set[str] = set()
    for raw in bound_emails:
        email = str(raw or "").strip().lower()
        if email and email not in seen_emails:
            seen_emails.add(email)
            deduped_emails.append(email)
    try:
        bound_count = int(data.get("bound_count") if data.get("bound_count") is not None else len(deduped_emails))
    except Exception:
        bound_count = len(deduped_emails)
    bound_count = max(0, min(MAX_BINDINGS_PER_PHONE, bound_count))
    if len(deduped_emails) > bound_count:
        bound_count = min(MAX_BINDINGS_PER_PHONE, len(deduped_emails))
    status = str(data.get("status") or "available").strip().lower()
    if status not in {"available", "invalid", "disabled", "full"}:
        status = "available"
    if status == "full" and bound_count < MAX_BINDINGS_PER_PHONE:
        status = "available"
    if bound_count >= MAX_BINDINGS_PER_PHONE and status not in {"invalid", "disabled"}:
        status = "full"
    phone = str(data.get("phone_number") or data.get("phone") or "").strip()
    return {
        "id": str(data.get("id") or uuid.uuid4().hex),
        "phone_number": phone,
        "phone_key": normalize_phone_key(phone),
        "sms_url": str(data.get("sms_url") or data.get("smsUrl") or "").strip(),
        "status": status,
        "bound_count": bound_count,
        "bound_emails": deduped_emails[:MAX_BINDINGS_PER_PHONE],
        "invalid_reason": str(data.get("invalid_reason") or "").strip(),
        "note": str(data.get("note") or "").strip(),
        "created_at": float(created_at or _now()),
        "updated_at": float(data.get("updated_at") or created_at or _now()),
        "last_used_at": data.get("last_used_at"),
    }


def _with_computed_status(item: dict[str, Any]) -> dict[str, Any]:
    data = _normalize_item(item)
    if data["status"] not in {"invalid", "disabled"}:
        data["status"] = "full" if int(data.get("bound_count") or 0) >= MAX_BINDINGS_PER_PHONE else "available"
    data["remaining"] = max(0, MAX_BINDINGS_PER_PHONE - int(data.get("bound_count") or 0))
    data["max_bindings"] = MAX_BINDINGS_PER_PHONE
    return data


def list_phones() -> list[dict[str, Any]]:
    with _LOCK:
        return [_with_computed_status(item) for item in _raw_items()]


def get_phone(item_id: str) -> dict[str, Any] | None:
    target = str(item_id or "").strip()
    if not target:
        return None
    with _LOCK:
        for item in _raw_items():
            if str(item.get("id") or "") == target:
                return _with_computed_status(item)
    return None


def upsert_phone(payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_item(payload)
    if not item["phone_number"]:
        raise ValueError("手机号不能为空")
    if not item["sms_url"]:
        raise ValueError("接码链接不能为空")
    item["updated_at"] = _now()
    with _LOCK:
        items = _raw_items()
        target_id = str(item.get("id") or "")
        target_key = item["phone_key"]
        for index, existing in enumerate(items):
            if str(existing.get("id") or "") == target_id or str(existing.get("phone_key") or "") == target_key:
                item["id"] = str(existing.get("id") or item["id"])
                item["created_at"] = existing.get("created_at") or item["created_at"]
                items[index] = item
                _save_items(items)
                return _with_computed_status(item)
        items.insert(0, item)
        _save_items(items)
        return _with_computed_status(item)


def update_phone(item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    target = str(item_id or "").strip()
    if not target:
        raise ValueError("手机号 ID 不能为空")
    with _LOCK:
        items = _raw_items()
        for index, existing in enumerate(items):
            if str(existing.get("id") or "") != target:
                continue
            merged = dict(existing)
            merged.update(dict(updates or {}))
            merged["id"] = target
            merged["updated_at"] = _now()
            item = _normalize_item(merged)
            if not item["phone_number"]:
                raise ValueError("手机号不能为空")
            if not item["sms_url"]:
                raise ValueError("接码链接不能为空")
            items[index] = item
            _save_items(items)
            return _with_computed_status(item)
    raise KeyError("手机号不存在")


def delete_phones(ids: list[str]) -> int:
    targets = {str(item or "").strip() for item in ids or [] if str(item or "").strip()}
    if not targets:
        return 0
    with _LOCK:
        items = _raw_items()
        kept = [item for item in items if str(item.get("id") or "") not in targets]
        deleted = len(items) - len(kept)
        if deleted:
            _save_items(kept)
        return deleted


def parse_import_lines(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"\s*-{4,}\s*", line, maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"导入格式无效: {line[:80]}")
        phone, sms_url = parts[0].strip(), parts[1].strip()
        if not phone or not sms_url:
            raise ValueError(f"导入格式无效: {line[:80]}")
        entries.append({"phone_number": phone, "sms_url": sms_url})
    return entries


def import_phones(text: str) -> dict[str, Any]:
    parsed = parse_import_lines(text)
    with _LOCK:
        items = _raw_items()
        known = {str(item.get("phone_key") or "") for item in items}
        added: list[dict[str, Any]] = []
        skipped = 0
        for entry in parsed:
            item = _normalize_item(entry)
            if not item["phone_key"] or item["phone_key"] in known:
                skipped += 1
                continue
            known.add(item["phone_key"])
            items.insert(0, item)
            added.append(_with_computed_status(item))
        if added:
            _save_items(items)
        return {
            "added": added,
            "added_count": len(added),
            "skipped_count": skipped,
            "total": len(items),
            "items": [_with_computed_status(item) for item in items],
        }


def acquire_available_phone(email: str = "") -> dict[str, Any] | None:
    normalized_email = str(email or "").strip().lower()
    with _LOCK:
        items = _raw_items()
        for index, item in enumerate(items):
            data = _with_computed_status(item)
            if data["status"] != "available":
                continue
            if normalized_email and normalized_email in set(data.get("bound_emails") or []):
                continue
            data["last_used_at"] = _now()
            data["updated_at"] = _now()
            items[index] = _normalize_item(data)
            _save_items(items)
            return _with_computed_status(data)
    return None


def mark_phone_bound(item_id: str, email: str = "") -> dict[str, Any] | None:
    target = str(item_id or "").strip()
    if not target:
        return None
    normalized_email = str(email or "").strip().lower()
    with _LOCK:
        items = _raw_items()
        for index, item in enumerate(items):
            if str(item.get("id") or "") != target:
                continue
            data = _normalize_item(item)
            previous_count = int(data.get("bound_count") or 0)
            emails = list(data.get("bound_emails") or [])
            email_added = bool(normalized_email and normalized_email not in emails)
            if email_added:
                emails.append(normalized_email)
            data["bound_emails"] = emails[:MAX_BINDINGS_PER_PHONE]
            next_count = previous_count + (1 if email_added else 0)
            data["bound_count"] = min(MAX_BINDINGS_PER_PHONE, max(next_count, len(data["bound_emails"])))
            data["last_used_at"] = _now()
            data["updated_at"] = _now()
            if int(data["bound_count"]) >= MAX_BINDINGS_PER_PHONE and data["status"] not in {"invalid", "disabled"}:
                data["status"] = "full"
            items[index] = _normalize_item(data)
            _save_items(items)
            return _with_computed_status(data)
    return None


def mark_phone_invalid(item_id: str, reason: str = "") -> dict[str, Any] | None:
    target = str(item_id or "").strip()
    if not target:
        return None
    with _LOCK:
        items = _raw_items()
        for index, item in enumerate(items):
            if str(item.get("id") or "") != target:
                continue
            data = _normalize_item(item)
            data["status"] = "invalid"
            data["invalid_reason"] = str(reason or "不可用").strip()
            data["updated_at"] = _now()
            items[index] = data
            _save_items(items)
            return _with_computed_status(data)
    return None
