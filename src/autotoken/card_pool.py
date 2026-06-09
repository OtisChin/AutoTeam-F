"""Compatibility wrapper for ``autotoken.payments.card_pool``."""

from __future__ import annotations

import sys as _sys

from autotoken.payments import card_pool as _impl

_sys.modules[__name__] = _impl
