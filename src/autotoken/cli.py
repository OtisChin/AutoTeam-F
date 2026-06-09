"""Compatibility wrapper for ``autotoken.interfaces.cli``."""

from __future__ import annotations

import sys as _sys

from autotoken.interfaces import cli as _impl

_sys.modules[__name__] = _impl
