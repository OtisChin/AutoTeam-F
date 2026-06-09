"""Compatibility wrapper for ``autotoken.auth.manual_account``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import manual_account as _impl

_sys.modules[__name__] = _impl
