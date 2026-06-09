"""GoPay Pro script log event parsing helpers."""

from __future__ import annotations

import re
from typing import Any


def text_has_waf_block(value: Any) -> bool:
    text = str(value or "").lower()
    return "waf block page" in text or "domain-config-1256704386.cos.accelerate.myqcloud" in text


def text_has_register_ratelimit(value: Any) -> bool:
    text = str(value or "").lower()
    return "ratelimited" in text or "rate limit" in text or "限流" in text


def register_ratelimited_slots_from_log(log_text: str) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    for line in str(log_text or "").splitlines():
        if not text_has_register_ratelimit(line):
            continue
        match = re.search(r"\[(slot-[^\]\s]+)\]", line)
        if not match:
            continue
        slot_id = match.group(1)
        if slot_id in seen:
            continue
        seen.add(slot_id)
        slots.append(slot_id)
    return slots


def harvest_started_slots(log_text: str) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\[(slot-[^\]\s]+)\]\s+开\s*Plus", str(log_text or "")):
        slot_id = match.group(1)
        if slot_id in seen:
            continue
        seen.add(slot_id)
        slots.append(slot_id)
    return slots


def text_has_token_invalidated(value: Any) -> bool:
    text = str(value or "").lower()
    return "token_invalidated" in text or "authentication token has been invalidated" in text


def text_has_chatgpt_checkout_unauthorized(value: Any) -> bool:
    text = str(value or "").lower()
    return "chatgpt checkout 401" in text


def slot_log_has_token_invalidated(log_text: str, slot_id: str) -> bool:
    if not slot_id:
        return False
    pattern = re.compile(
        rf"\[{re.escape(slot_id)}\].*(token_invalidated|authentication token has been invalidated)",
        re.IGNORECASE,
    )
    return bool(pattern.search(str(log_text or "")))


def slot_log_has_chatgpt_checkout_unauthorized(log_text: str, slot_id: str) -> bool:
    if not slot_id:
        return False
    lines = str(log_text or "").splitlines()
    for index, line in enumerate(lines):
        if not re.search(rf"\[{re.escape(slot_id)}\]", line):
            continue
        if "chatgpt checkout 401" not in line.lower():
            continue
        block = "\n".join(lines[index : index + 12])
        if text_has_chatgpt_checkout_unauthorized(block):
            return True
    return False


def harvest_checkout_unauthorized_slots(log_text: str) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    for line in str(log_text or "").splitlines():
        if not text_has_chatgpt_checkout_unauthorized(line):
            continue
        match = re.search(r"\[(slot-[^\]\s]+)\]", line)
        if not match:
            continue
        slot_id = match.group(1)
        if slot_id in seen:
            continue
        seen.add(slot_id)
        slots.append(slot_id)
    return slots


def midtrans_charge_202_slots(log_text: str) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"\[(slot-[^\]\s]+)\].*midtrans\s+charge\s+denied:.*\bcode=202\b", re.IGNORECASE)
    for match in pattern.finditer(str(log_text or "")):
        slot_id = match.group(1)
        if slot_id in seen:
            continue
        seen.add(slot_id)
        slots.append(slot_id)
    return slots


def slot_log_has_success(log_text: str, slot_id: str) -> bool:
    if not slot_id:
        return False
    pattern = re.compile(rf"\[{re.escape(slot_id)}\].*(✅\s*Plus\s*开通成功|chatgpt verify ok|换绑完成)", re.IGNORECASE)
    return bool(pattern.search(str(log_text or "")))


def harvest_terminal_events(log_text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    terminal_slots: set[str] = set()
    for line in str(log_text or "").splitlines():
        match = re.search(r"\[(slot-[^\]\s]+)\]\s+(.*)", line)
        if not match:
            continue
        slot_id = match.group(1)
        message = match.group(2)
        if slot_id in terminal_slots:
            continue
        lower = message.lower()
        kind = ""
        if "✅" in message and "Plus 开通成功" in message:
            kind = "success"
        elif "账号无免费试用资格" in message or "无免费试用资格" in message or "no_trial" in lower:
            kind = "no_trial"
        elif text_has_token_invalidated(message):
            kind = "token_invalidated"
        elif text_has_chatgpt_checkout_unauthorized(message):
            kind = "checkout_unauthorized"
        if kind:
            terminal_slots.add(slot_id)
            events.append({"kind": kind, "slot_id": slot_id})
    return events


def payment_validate_failed_slots(log_text: str) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"\[(slot-[^\]\s]+)\].*Plus\s+支付失败:\s*payment/validate\s+重试后仍失败", re.IGNORECASE)
    for match in pattern.finditer(str(log_text or "")):
        slot_id = match.group(1)
        if slot_id in seen:
            continue
        seen.add(slot_id)
        slots.append(slot_id)
    return slots
