"""Compatibility wrapper for ``autotoken.payments.paypal_bind_executor``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import paypal_bind_executor as _impl

_sys.modules[__name__] = _impl
