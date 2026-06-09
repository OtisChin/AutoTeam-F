"""GoPay Pro pool, token, and slot rule helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

NUMBER_COOLDOWN_PREFIX = "# autotoken-cooldown "
NUMBER_COOLDOWN_KEY = "register_ratelimited_numbers"


def normalize_access_token(raw_value: Any) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and "accessToken" in raw:
        try:
            parsed = json.loads(raw)
            token = parsed.get("accessToken") if isinstance(parsed, dict) else ""
            if token:
                raw = str(token).strip()
        except Exception:
            pass
    raw = re.sub(r"^Bearer\s+", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"^[\"']+|[\"',;\s]+$", "", raw).strip()
    return raw


def pool_line_phone(line: str) -> str:
    return str(line or "").split("----", 1)[0].strip()


def phone_key(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def pool_cooldown_original_line(line: str) -> tuple[int, str]:
    stripped = str(line or "").strip()
    if not stripped.startswith(NUMBER_COOLDOWN_PREFIX):
        return 0, ""
    match = re.match(r"^#\s*autotoken-cooldown\s+until=(\d+)\s+reason=\S+\s+(.+)$", stripped)
    if not match:
        return 0, ""
    try:
        until = int(match.group(1))
    except Exception:
        until = 0
    return until, match.group(2).strip()


def token_fingerprint(value: Any) -> str:
    token = normalize_access_token(value)
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else ""


def build_token_map_payload(token_items: list[dict[str, str]], *, updated_at: int) -> dict[str, Any]:
    tokens: dict[str, dict[str, str]] = {}
    for item in token_items:
        fingerprint = token_fingerprint(item.get("access_token"))
        email = str(item.get("email") or "").strip()
        if not fingerprint or not email:
            continue
        tokens[fingerprint] = {
            "email": email,
            "account_id": str(item.get("account_id") or "").strip(),
            "auth_file": str(item.get("auth_file") or "").strip(),
        }
    return {
        "version": 1,
        "updated_at": int(updated_at),
        "tokens": tokens,
    }


def slot_email_from_token_map(state: dict[str, Any], token_map: dict[str, Any], slot_id: str) -> str:
    slots = state.get("slots") if isinstance(state, dict) else {}
    if not isinstance(slots, dict):
        return ""
    slot = slots.get(slot_id)
    if not isinstance(slot, dict):
        slot = next(
            (
                item
                for key, item in slots.items()
                if isinstance(item, dict) and str(item.get("id") or key or "") == slot_id
            ),
            None,
        )
    if not isinstance(slot, dict):
        return ""
    fingerprint = token_fingerprint(slot.get("access_token") or slot.get("accessToken") or "")
    if not fingerprint:
        return ""
    entries = token_map.get("tokens") if isinstance(token_map, dict) else {}
    entry = entries.get(fingerprint) if isinstance(entries, dict) else None
    return str(entry.get("email") or "").strip() if isinstance(entry, dict) else ""


def local_phone(value: str) -> str:
    text = str(value or "").strip()
    return re.sub(r"^\+?62", "", text)


def slot_pick_score(slot_key: str, slot: dict, expected_key: str) -> tuple[int, int, int, int]:
    state_priority = {
        "WALLET_READY": 90,
        "WALLET_WAITING": 80,
        "GOPAY_REGISTERING": 70,
        "PLUS_PAYING": 60,
        "RELEASED": 50,
        "NO_TRIAL": 40,
        "FAILED": 10,
        "EMPTY": 0,
    }
    try:
        updated = int(slot.get("updated_at") or 0)
    except Exception:
        updated = 0
    return (
        1 if slot_key == expected_key else 0,
        1 if slot.get("refresh_token") else 0,
        state_priority.get(str(slot.get("state") or ""), 0),
        updated,
    )


def pool_line_access_token(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    if cleaned.startswith("{"):
        try:
            payload = json.loads(cleaned)
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            token = (
                payload.get("access_token")
                or payload.get("accessToken")
                or (
                    (payload.get("tokens") or {}).get("access_token") if isinstance(payload.get("tokens"), dict) else ""
                )
            )
            return normalize_access_token(token)
    return normalize_access_token(cleaned)


def mask_phone(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 7:
        return text
    return f"{text[:5]}****{text[-3:]}"


def slot_index(slot: dict | str) -> int:
    raw = slot if isinstance(slot, str) else slot.get("id")
    match = re.search(r"(\d+)$", str(raw or ""))
    return int(match.group(1)) if match else 0


def normalize_slots_for_number_lines(
    slots: dict[str, Any],
    number_lines: list[str],
    *,
    now: int,
) -> tuple[dict[str, Any], int]:
    if number_lines:
        normalized_slots: dict[str, dict[str, Any]] = {}
        for index, line in enumerate(number_lines, start=1):
            expected_id = f"slot-{index:02d}"
            phone = pool_line_phone(line)
            normalized_slots[expected_id] = normalized_slot_for_number_line(
                slots,
                expected_id=expected_id,
                line=line,
                phone=phone,
                now=now,
            )

        changed = json.dumps(slots, sort_keys=True, ensure_ascii=False) != json.dumps(
            normalized_slots, sort_keys=True, ensure_ascii=False
        )
        return normalized_slots, 1 if changed else 0

    normalized_slots: dict[str, Any] = {}
    changed = 0
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            normalized_slots[slot_key] = slot
            continue
        normalized = dict(slot)
        expected_id = str(slot_key or "").strip()
        if expected_id and str(normalized.get("id") or "") != expected_id:
            normalized["id"] = expected_id
            changed += 1
        normalized_slots[slot_key] = normalized
    return normalized_slots, changed


def normalized_slot_for_number_line(
    slots: dict[str, Any],
    *,
    expected_id: str,
    line: str,
    phone: str,
    now: int,
) -> dict[str, Any]:
    key = phone_key(phone)
    candidates: list[tuple[str, dict]] = []
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            continue
        slot_phone_keys = {
            phone_key(slot.get("full_phone")),
            phone_key(slot.get("phone")),
            phone_key(pool_line_phone(str(slot.get("card") or ""))),
        }
        if key and key in slot_phone_keys:
            candidates.append((str(slot_key), slot))

    if candidates:
        _, picked_slot = max(
            candidates,
            key=lambda item: slot_pick_score(item[0], item[1], expected_id),
        )
        normalized = dict(picked_slot)
    else:
        normalized = {
            "state": "EMPTY",
            "updated_at": int(now),
        }

    normalized["id"] = expected_id
    normalized["card"] = line
    normalized["full_phone"] = phone
    normalized["phone"] = normalized.get("phone") or local_phone(phone)
    return normalized


def ready_slot_prefix_from_slots(slots: dict[str, Any], required: int) -> tuple[int, int]:
    ready_indexes = sorted(
        slot_index(slot)
        for slot in slots.values()
        if isinstance(slot, dict) and str(slot.get("state") or "") == "WALLET_READY"
    )
    ready_indexes = [index for index in ready_indexes if index > 0]
    if required > 0 and len(ready_indexes) >= required:
        return len(ready_indexes), ready_indexes[required - 1]
    return len(ready_indexes), (ready_indexes[-1] if ready_indexes else 0)


def release_no_trial_slots(
    slots: dict[str, Any],
    *,
    round_tokens: set[str] | None,
    slot_ids: set[str] | None,
    now: int,
) -> tuple[dict[str, Any], int]:
    normalized_tokens = {normalize_access_token(token) for token in (round_tokens or set())}
    normalized_tokens.discard("")
    wanted_slots = {str(slot_id or "").strip() for slot_id in (slot_ids or set()) if str(slot_id or "").strip()}
    next_slots: dict[str, Any] = {}
    changed = 0
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            next_slots[slot_key] = slot
            continue
        next_slot = dict(slot)
        slot_id = str(next_slot.get("id") or "")
        token = normalize_access_token(next_slot.get("access_token") or next_slot.get("accessToken") or "")
        should_release = next_slot.get("state") == "NO_TRIAL" and (
            round_tokens is None or (slot_ids is not None and slot_id in wanted_slots) or token in normalized_tokens
        )
        if should_release:
            next_slot["state"] = "WALLET_READY"
            next_slot["updated_at"] = int(now)
            changed += 1
        next_slots[slot_key] = next_slot
    return next_slots, changed


def mark_midtrans_charge_202_slots(
    slots: dict[str, Any],
    slot_ids: list[str] | set[str],
    *,
    now: int,
) -> tuple[dict[str, Any], list[str]]:
    wanted = {str(slot_id or "").strip() for slot_id in slot_ids if str(slot_id or "").strip()}
    if not wanted:
        return slots, []
    next_slots: dict[str, Any] = {}
    marked: list[str] = []
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            next_slots[slot_key] = slot
            continue
        next_slot = dict(slot)
        slot_id = str(next_slot.get("id") or slot_key or "")
        if slot_id in wanted:
            next_slot["midtrans_charge_202"] = True
            next_slot["midtrans_charge_202_at"] = int(now)
            next_slot["updated_at"] = int(now)
            marked.append(slot_id)
        next_slots[slot_key] = next_slot
    return next_slots, marked


def slots_in_states(slots: dict[str, Any], slot_ids: list[str], states: set[str]) -> list[str]:
    remaining: list[str] = []
    wanted = {str(item or "").strip() for item in slot_ids if str(item or "").strip()}
    for slot_id in wanted:
        slot = slots.get(slot_id)
        if isinstance(slot, dict) and str(slot.get("state") or "") in states:
            remaining.append(slot_id)
    remaining.sort(key=slot_index)
    return remaining


def reset_unusable_ready_slots(slots: dict[str, Any], *, now: int) -> tuple[dict[str, Any], int]:
    next_slots: dict[str, Any] = {}
    changed = 0
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            next_slots[slot_key] = slot
            continue
        next_slot = dict(slot)
        if next_slot.get("state") == "WALLET_READY":
            access_token = normalize_access_token(next_slot.get("access_token") or next_slot.get("accessToken") or "")
            refresh_token = normalize_access_token(next_slot.get("refresh_token") or next_slot.get("refreshToken") or "")
            error = str(next_slot.get("error") or "")
            if not (access_token and refresh_token and "缺少 refresh_token" not in error):
                next_slot["state"] = "FAILED"
                next_slot["error"] = "AutoToken: WALLET_READY 缺少可刷新 GoPay token，已重置为 FAILED，等待 reg 重建稳定号"
                next_slot["updated_at"] = int(now)
                changed += 1
        next_slots[slot_key] = next_slot
    return next_slots, changed


def reset_stuck_paying_slots(slots: dict[str, Any], *, now: int) -> tuple[dict[str, Any], int]:
    next_slots: dict[str, Any] = {}
    changed = 0
    for slot_key, slot in slots.items():
        if not isinstance(slot, dict):
            next_slots[slot_key] = slot
            continue
        next_slot = dict(slot)
        if next_slot.get("state") == "PLUS_PAYING" and str(next_slot.get("error") or "").strip():
            next_slot["state"] = "WALLET_READY"
            next_slot["updated_at"] = int(now)
            changed += 1
        next_slots[slot_key] = next_slot
    return next_slots, changed


def build_status_payload(
    *,
    root: str,
    exists: bool,
    config: dict[str, Any],
    state: dict[str, Any],
    number_lines: list[str],
    token_lines: list[str],
    waf_cooldown: dict[str, Any],
    tasks: list[dict[str, Any]],
    commands: set[str],
) -> dict[str, Any]:
    slots = status_slots(state)
    state_counts = status_state_counts(slots)
    pool_config = config.get("pool") if isinstance(config.get("pool"), dict) else {}
    active_number_count = len(active_pool_lines(number_lines))
    return {
        "root": str(root),
        "exists": bool(exists),
        "config": {
            "slots": active_number_count,
            "concurrency": int(pool_config.get("concurrency") or 0),
            "gptMode": str(pool_config.get("gpt_mode") or ""),
            "numberPoolFile": str(pool_config.get("number_pool_file") or "pool_numbers.txt"),
            "tokenFile": str(pool_config.get("provided_tokens_file") or "pool_tokens.txt"),
        },
        "counts": {
            "numbers": active_number_count,
            "tokens": len(active_pool_lines(token_lines)),
        },
        "cooldowns": {
            "registerWafUntil": waf_cooldown.get("until"),
            "registerWafRemainingSeconds": waf_cooldown.get("remaining_seconds"),
            "registerWafReason": waf_cooldown.get("reason"),
        },
        "commands": sorted(commands),
        "slots": slots,
        "stateCounts": state_counts,
        "tasks": tasks[:8],
    }


def status_slots(state: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    state_slots = state.get("slots") if isinstance(state, dict) else {}
    for slot_id, slot in (state_slots or {}).items():
        if not isinstance(slot, dict):
            continue
        slots.append(
            {
                **slot,
                "id": str(slot_id or slot.get("id") or ""),
                "displayPhone": mask_phone(slot.get("full_phone") or slot.get("phone") or ""),
                "midtransCharge202": bool(slot.get("midtrans_charge_202")),
                "midtransCharge202At": slot.get("midtrans_charge_202_at") or 0,
            }
        )
    slots.sort(key=lambda item: str(item.get("id") or ""))
    return slots


def status_state_counts(slots: list[dict[str, Any]]) -> dict[str, int]:
    state_counts: dict[str, int] = {}
    for slot in slots:
        key = str(slot.get("state") or "UNKNOWN")
        state_counts[key] = state_counts.get(key, 0) + 1
    return state_counts


def active_pool_lines(lines: list[str]) -> list[str]:
    return [str(line) for line in lines if str(line or "").strip() and not str(line).strip().startswith("#")]
