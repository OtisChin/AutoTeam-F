"""Compatibility wrapper for ``autotoken.auth.codex_auth``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import codex_auth as _impl

_sys.modules[__name__] = _impl
