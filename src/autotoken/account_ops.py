"""Compatibility wrapper for ``autotoken.storage.account_ops``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import account_ops as _impl

_sys.modules[__name__] = _impl
