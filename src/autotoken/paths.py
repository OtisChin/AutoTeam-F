"""Compatibility wrapper for ``autotoken.core.paths``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import paths as _impl

_sys.modules[__name__] = _impl
