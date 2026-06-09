"""Environment variable compatibility helpers."""

from __future__ import annotations

import os
from pathlib import Path

from autotoken.core.textio import read_text

ENV_PREFIX_ALIASES = (("AUTOTOKEN_", "AUTOTEAM_"),)
ENV_FILE_MAX_BYTES = 256 * 1024


def install_legacy_env_aliases(environ: dict[str, str] | None = None) -> None:
    """Expose legacy ``AUTOTEAM_*`` environment variables under ``AUTOTOKEN_*`` names."""

    target = os.environ if environ is None else environ
    for canonical_prefix, legacy_prefix in ENV_PREFIX_ALIASES:
        for key, value in list(target.items()):
            if not key.startswith(legacy_prefix):
                continue
            canonical_key = canonical_prefix + key[len(legacy_prefix) :]
            target.setdefault(canonical_key, value)


def set_env_default_with_legacy_alias(key: str, value: str, environ: dict[str, str] | None = None) -> None:
    """Set an env default and mirror old ``AUTOTEAM_*`` keys to ``AUTOTOKEN_*``."""

    target = os.environ if environ is None else environ
    if key.startswith("AUTOTOKEN_"):
        legacy_key = "AUTOTEAM_" + key[len("AUTOTOKEN_") :]
        if key not in target and legacy_key in target:
            target[key] = target[legacy_key]
    target.setdefault(key, value)
    if key.startswith("AUTOTEAM_"):
        target.setdefault("AUTOTOKEN_" + key[len("AUTOTEAM_") :], target[key])


def read_env_lines(path: str | Path, *, max_bytes: int = ENV_FILE_MAX_BYTES) -> list[str]:
    """Read a small dotenv-style file as lines."""

    env_path = Path(path)
    try:
        if not env_path.exists():
            return []
        if max_bytes > 0 and env_path.stat().st_size > max_bytes:
            raise ValueError(f".env 文件过大，拒绝读取: {env_path}")
        return read_text(env_path).splitlines()
    except FileNotFoundError:
        return []
