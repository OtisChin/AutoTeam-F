"""Compatibility wrapper for ``autotoken.payments.bind_executor``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import bind_executor as _impl

_sys.modules[__name__] = _impl
