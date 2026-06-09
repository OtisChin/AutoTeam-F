"""Compatibility wrapper for ``autotoken.interfaces.api``."""

from __future__ import annotations

import sys as _sys

from autotoken.interfaces import api as _impl

_sys.modules[__name__] = _impl
