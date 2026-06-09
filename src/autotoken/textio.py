"""Compatibility wrapper for ``autotoken.core.textio``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import textio as _impl

_sys.modules[__name__] = _impl
