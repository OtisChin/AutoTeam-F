"""Compatibility wrapper for ``autotoken.payments.gopay_auto_register``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import gopay_auto_register as _impl

_sys.modules[__name__] = _impl
