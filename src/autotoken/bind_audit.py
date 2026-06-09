"""Compatibility wrapper for ``autotoken.payments.bind_audit``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import bind_audit as _impl

_sys.modules[__name__] = _impl
