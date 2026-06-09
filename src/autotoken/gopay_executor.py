"""Compatibility wrapper for ``autotoken.payments.gopay_executor``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import gopay_executor as _impl

_sys.modules[__name__] = _impl
