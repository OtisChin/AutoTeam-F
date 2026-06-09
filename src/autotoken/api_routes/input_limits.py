"""Shared request-size guards for API text payloads."""

from fastapi import HTTPException


def validate_text_payload_limits(
    text: str,
    *,
    max_bytes: int,
    max_lines: int,
    label: str,
) -> list[str]:
    raw_text = str(text or "")
    if len(raw_text.encode("utf-8", errors="ignore")) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"{label}内容过大，最多支持 {max_mb}MB 文本")

    lines = raw_text.splitlines()
    if len(lines) > max_lines:
        raise HTTPException(status_code=400, detail=f"{label}行数过多，最多支持 {max_lines} 行")
    return lines


def validate_list_payload_limit(values: list | tuple | None, *, max_items: int, label: str) -> None:
    if len(values or []) > max_items:
        raise HTTPException(status_code=400, detail=f"{label}条目过多，最多支持 {max_items} 条")
