"""Compatibility wrapper for ``autotoken.payments.protocol_card_executor``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import protocol_card_executor as _impl

_sys.modules[__name__] = _impl
