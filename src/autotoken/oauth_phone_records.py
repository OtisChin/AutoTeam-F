"""Persistent audit records for OAuth add-phone dynamic SMS numbers."""

from __future__ import annotations

import time
import uuid
from typing import Any

from autoteam import sqlite_store

NAMESPACE = "oauth_phone_records"
KEY = "records"
MAX_RECORDS = 1000


def _now() -> float:
    return time.time()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _load() -> list[dict[str, Any]]:
    data = sqlite_store.get_json(NAMESPACE, KEY, default=[])
    return data if isinstance(data, list) else []


def _save(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sqlite_store.set_json(NAMESPACE, KEY, items[:MAX_RECORDS])
    return items[:MAX_RECORDS]


def list_records(limit: int = 300) -> list[dict[str, Any]]:
    limit = max(1, min(1000, int(limit or 300)))
    return _load()[:limit]


def record_acquired(payload: dict[str, Any]) -> dict[str, Any]:
    activation_id = _clean_text(payload.get("activation_id"))
    provider = _clean_text(payload.get("provider") or payload.get("source"))
    record_id = _clean_text(payload.get("id")) or (
        f"{provider}:{activation_id}" if provider and activation_id else str(uuid.uuid4())
    )
    now = _now()
    item = {
        "id": record_id,
        "provider": provider,
        "activation_id": activation_id,
        "phone_number": _clean_text(payload.get("phone_number") or payload.get("phone")),
        "country": _clean_text(payload.get("country") or payload.get("country_id")),
        "service": _clean_text(payload.get("service")),
        "operator": _clean_text(payload.get("operator")),
        "price": _clean_text(payload.get("price")),
        "currency": _clean_text(payload.get("currency") or "USD"),
        "price_source": _clean_text(payload.get("price_source")),
        "price_limit": _clean_text(payload.get("price_limit")),
        "email": _clean_text(payload.get("email")),
        "status": _clean_text(payload.get("status") or "acquired"),
        "reason": _clean_text(payload.get("reason")),
        "created_at": float(payload.get("created_at") or now),
        "updated_at": now,
        "finished_at": None,
        "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
    }
    items = _load()
    next_items = [item] + [old for old in items if _clean_text(old.get("id")) != record_id]
    _save(next_items)
    return item


def update_record(record_id: str, **updates: Any) -> dict[str, Any] | None:
    record_id = _clean_text(record_id)
    if not record_id:
        return None
    now = _now()
    items = _load()
    updated: dict[str, Any] | None = None
    for item in items:
        if _clean_text(item.get("id")) != record_id:
            continue
        for key, value in updates.items():
            if value is None:
                continue
            item[key] = value
        item["updated_at"] = now
        if _clean_text(item.get("status")) in {"success", "finished", "cancelled", "failed", "invalid", "cooldown"}:
            item["finished_at"] = item.get("finished_at") or now
        updated = item
        break
    if updated is not None:
        _save(items)
    return updated
