"""Compatibility wrapper for ``autotoken.core.cancel_signal``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import cancel_signal as _impl

_sys.modules[__name__] = _impl
