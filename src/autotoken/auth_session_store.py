"""Compatibility wrapper for ``autotoken.storage.auth_session_store``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import auth_session_store as _impl

_sys.modules[__name__] = _impl
