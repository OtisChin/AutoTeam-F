"""Compatibility wrapper for ``autotoken.storage.register_failures``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import register_failures as _impl

_sys.modules[__name__] = _impl
