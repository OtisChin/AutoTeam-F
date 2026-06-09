"""Compatibility wrapper for ``autotoken.commerce.trade``."""

from __future__ import annotations

import sys as _sys

from autotoken.commerce import trade as _impl

_sys.modules[__name__] = _impl
