"""Compatibility wrapper for ``autotoken.payments.paypal_protocol_signup``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import paypal_protocol_signup as _impl

_sys.modules[__name__] = _impl
