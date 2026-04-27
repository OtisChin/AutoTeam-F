"""卡池持久化与查询。"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
CARD_POOL_FILE = PROJECT_ROOT / "data" / "card_pool.json"

POOL_TYPES = {"redeem", "card"}
STATUSES = {"unused", "used", "expired"}


def _default_pool():
    return {"redeem": [], "card": []}


def _ensure_parent():
    CARD_POOL_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_card_pool():
    _ensure_parent()
    if not CARD_POOL_FILE.exists():
        return _default_pool()
    raw = read_text(CARD_POOL_FILE).strip()
    if not raw:
        return _default_pool()
    data = json.loads(raw)
    return {
        "redeem": data.get("redeem", []) if isinstance(data.get("redeem", []), list) else [],
        "card": data.get("card", []) if isinstance(data.get("card", []), list) else [],
    }


def save_card_pool(data):
    _ensure_parent()
    write_text(CARD_POOL_FILE, json.dumps(data, indent=2, ensure_ascii=False))


def _normalize_status(status: str | None) -> str:
    status = (status or "").strip().lower()
    return status if status in STATUSES else "unused"


def _normalize_pool_type(pool_type: str) -> str:
    pool_type = (pool_type or "").strip().lower()
    if pool_type not in POOL_TYPES:
        raise ValueError("无效的卡池类型")
    return pool_type


def make_item(pool_type: str, value: str, provider: str = "", status: str = "unused", expires_at: str = ""):
    return {
        "id": uuid.uuid4().hex,
        "type": _normalize_pool_type(pool_type),
        "value": value.strip(),
        "provider": provider.strip(),
        "status": _normalize_status(status),
        "created_at": time.time(),
        "expires_at": expires_at.strip(),
        "used_by": "",
        "used_at": None,
        "meta": {},
    }


def _to_timestamp(value) -> float:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0
    for parser in (
        lambda: time.mktime(time.strptime(text, "%Y-%m-%d %H:%M")),
        lambda: time.mktime(time.strptime(text, "%Y-%m-%dT%H:%M:%S")),
        lambda: time.mktime(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")),
    ):
        try:
            return parser()
        except ValueError:
            pass
    return 0


def _refresh_expired_items(data):
    now = time.time()
    changed = False
    for item in data.get("card", []):
        expires_at = _to_timestamp(item.get("expires_at"))
        if expires_at and expires_at <= now and item.get("status") != "expired":
            item["status"] = "expired"
            changed = True
    if changed:
        save_card_pool(data)
    return data


def _parse_card_blocks(text: str):
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    items = []
    for block in blocks:
        fields = {}
        for line in block.splitlines():
            raw = line.strip()
            if not raw or ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        card_number = fields.get("卡号 card number") or fields.get("card number")
        if not card_number:
            continue
        expiry = fields.get("有效期 expiry") or fields.get("expiry") or ""
        phone = fields.get("电话 phone") or fields.get("phone") or ""
        name = fields.get("姓名 name") or fields.get("name") or ""
        address = fields.get("地址 address") or fields.get("address") or ""
        sms_api = fields.get("接码 api") or fields.get("sms api") or ""
        cvv = fields.get("cvv") or ""
        meta = {
            "card": {},
            "content": {
                "card_number": card_number,
                "expiry_date": expiry,
                "cvv": cvv,
                "phone": phone,
                "name": name,
                "address": address,
                "sms_api": sms_api,
            },
        }
        items.append((card_number, expiry, meta))
    return items


def list_items(pool_type: str):
    data = _refresh_expired_items(load_card_pool())
    return data[_normalize_pool_type(pool_type)]


def import_text_lines(pool_type: str, text: str, provider: str = ""):
    pool_type = _normalize_pool_type(pool_type)
    data = load_card_pool()
    target = data[pool_type]
    known = {str(item.get("value", "")).strip() for item in target}
    added = []
    if pool_type == "card":
        for value, expiry, meta in _parse_card_blocks(text):
            if value in known:
                continue
            item = make_item(pool_type, value=value, provider=provider, expires_at=expiry)
            item["meta"] = meta
            target.insert(0, item)
            known.add(value)
            added.append(item)
        save_card_pool(data)
        return added
    for raw in text.splitlines():
        value = raw.strip()
        if not value or value in known:
            continue
        item = make_item(pool_type, value=value, provider=provider)
        target.insert(0, item)
        known.add(value)
        added.append(item)
    save_card_pool(data)
    return added


def delete_items(pool_type: str, ids: list[str]):
    pool_type = _normalize_pool_type(pool_type)
    data = load_card_pool()
    before = len(data[pool_type])
    id_set = set(ids)
    data[pool_type] = [item for item in data[pool_type] if item.get("id") not in id_set]
    save_card_pool(data)
    return before - len(data[pool_type])


def update_item(pool_type: str, item_id: str, **updates):
    pool_type = _normalize_pool_type(pool_type)
    data = load_card_pool()
    for item in data[pool_type]:
        if item.get("id") != item_id:
            continue
        if "provider" in updates:
            item["provider"] = str(updates["provider"] or "").strip()
        if "status" in updates:
            item["status"] = _normalize_status(updates["status"])
            if item["status"] != "used":
                item["used_by"] = ""
                item["used_at"] = None
            elif not item.get("used_at"):
                item["used_at"] = time.time()
        if "used_by" in updates:
            item["used_by"] = str(updates["used_by"] or "").strip()
        if "expires_at" in updates:
            item["expires_at"] = str(updates["expires_at"] or "").strip()
        if "meta" in updates and isinstance(updates["meta"], dict):
            item["meta"] = updates["meta"]
        save_card_pool(data)
        return item
    return None


def add_card_item(value: str, provider: str = "", status: str = "unused", expires_at: str = "", meta: dict | None = None):
    data = load_card_pool()
    item = make_item("card", value=value, provider=provider, status=status, expires_at=expires_at)
    item["meta"] = meta or {}
    data["card"].insert(0, item)
    save_card_pool(data)
    return item


def find_item(pool_type: str, item_id: str):
    pool_type = _normalize_pool_type(pool_type)
    data = _refresh_expired_items(load_card_pool())
    for item in data[pool_type]:
        if item.get("id") == item_id:
            return item
    return None


def stats_for(pool_type: str):
    items = list_items(pool_type)
    return {
        "total": len(items),
        "unused": sum(1 for item in items if item.get("status") == "unused"),
        "used": sum(1 for item in items if item.get("status") == "used"),
        "expired": sum(1 for item in items if item.get("status") == "expired"),
    }
