"""Compatibility wrapper for ``autotoken.storage.auth_index``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import auth_index as _impl

_sys.modules[__name__] = _impl
