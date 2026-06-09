"""Compatibility wrapper for ``autotoken.core.identity``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import identity as _impl

_sys.modules[__name__] = _impl
