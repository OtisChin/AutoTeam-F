"""Compatibility wrapper for ``autotoken.auth.invite``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import invite as _impl

_sys.modules[__name__] = _impl
