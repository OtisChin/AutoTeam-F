"""Compatibility wrapper for ``autotoken.auth.auth_prompts``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import auth_prompts as _impl

_sys.modules[__name__] = _impl
