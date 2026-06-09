"""Small file helpers shared by services and API modules."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from autotoken.core.textio import read_text

READ_LINES_FILE_MAX_BYTES = 2 * 1024 * 1024
READ_JSON_FILE_MAX_BYTES = 2 * 1024 * 1024


def read_json_file(path: Path, fallback: Any, *, max_bytes: int = READ_JSON_FILE_MAX_BYTES) -> Any:
    try:
        if path.exists() and max_bytes > 0 and path.stat().st_size > max_bytes:
            raise ValueError(f"JSON 文件过大，无法一次性读取: {path}")
        return json.loads(read_text(path))
    except Exception:
        return fallback


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_lines_file(path: Path, *, max_bytes: int = READ_LINES_FILE_MAX_BYTES) -> list[str]:
    try:
        if path.exists() and max_bytes > 0 and path.stat().st_size > max_bytes:
            raise ValueError(f"文件过大，无法一次性读取: {path}")
        return read_text(path).splitlines()
    except FileNotFoundError:
        return []


def active_non_comment_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def append_unique_non_comment_lines(path: Path, incoming: list[str]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = read_lines_file(path)
    existing = set(active_non_comment_lines(existing_lines))
    additions = []
    duplicates = []
    for raw in incoming or []:
        line = str(raw or "").strip()
        if not line or line.startswith("#"):
            continue
        if line in existing:
            duplicates.append(line)
            continue
        existing.add(line)
        additions.append(line)
    if additions:
        current = "\n".join(existing_lines).rstrip()
        next_text = f"{current}\n" if current else ""
        next_text += "\n".join(additions) + "\n"
        path.write_text(next_text, encoding="utf-8")
    return {"added": len(additions), "duplicates": len(duplicates)}
