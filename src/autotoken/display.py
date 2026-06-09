"""Compatibility wrapper for ``autotoken.core.display``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import display as _impl

_sys.modules[__name__] = _impl
