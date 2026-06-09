"""Compatibility wrapper for ``autotoken.payments.gopay_appium``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import gopay_appium as _impl

_sys.modules[__name__] = _impl
