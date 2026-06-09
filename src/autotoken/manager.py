"""Compatibility wrapper for ``autotoken.interfaces.manager``."""

from __future__ import annotations

import sys as _sys

from autotoken.interfaces import manager as _impl

_sys.modules[__name__] = _impl
