"""Compatibility wrapper for ``autotoken.storage.accounts``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import accounts as _impl

_sys.modules[__name__] = _impl
