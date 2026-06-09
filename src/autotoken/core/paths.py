"""Runtime paths shared by source and packaged executable builds."""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = _project_root()


def is_inside_directory(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def resolve_project_config_path(
    value: str | Path,
    *,
    project_root: Path | None = None,
    allow_absolute: bool = True,
) -> Path | None:
    """Resolve a configured file path, rejecting relative paths that escape the project root."""
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path if allow_absolute else None
    root = project_root or PROJECT_ROOT
    candidate = root / path
    return candidate if is_inside_directory(candidate, root) else None
