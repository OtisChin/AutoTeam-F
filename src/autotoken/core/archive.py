"""Helpers for safe archive member names."""

from __future__ import annotations

import re
from pathlib import Path


def safe_archive_member_name(
    name: object,
    *,
    fallback: str = "file",
    default_suffix: str = "",
    allowed_suffixes: set[str] | None = None,
    strip_paths: bool = True,
) -> str:
    filename = str(name or "").strip()
    if strip_paths:
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    else:
        filename = re.sub(r"[\\/]+", "_", filename)
    if not filename:
        filename = fallback

    path = Path(filename)
    suffix = path.suffix
    if allowed_suffixes is not None and suffix.lower() not in {item.lower() for item in allowed_suffixes}:
        suffix = default_suffix or sorted(allowed_suffixes)[0]
    elif not suffix and default_suffix:
        suffix = default_suffix

    fallback_stem = Path(fallback).stem or "file"
    stem = re.sub(r"[^A-Za-z0-9@._+-]+", "_", path.stem).strip("._") or fallback_stem
    return f"{stem}{suffix}"


def safe_archive_path_segment(value: object, *, fallback: str = "item") -> str:
    text = str(value or "").strip()
    segment = re.sub(r"[^A-Za-z0-9@._+-]+", "_", text).strip("._")
    return segment or fallback
