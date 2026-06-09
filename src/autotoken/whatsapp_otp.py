"""Compatibility wrapper for ``autotoken.payments.whatsapp_otp``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import whatsapp_otp as _impl

_sys.modules[__name__] = _impl
