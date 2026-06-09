"""Compatibility wrapper for ``autotoken.settings.admin_state``."""

from __future__ import annotations

import sys as _sys

from autotoken.settings import admin_state as _impl

_sys.modules[__name__] = _impl
