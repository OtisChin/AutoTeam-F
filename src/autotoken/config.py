"""Compatibility wrapper for ``autotoken.settings.config``."""

from __future__ import annotations

import sys as _sys

from autotoken.settings import config as _impl

_sys.modules[__name__] = _impl
