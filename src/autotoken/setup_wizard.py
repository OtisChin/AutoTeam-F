"""Compatibility wrapper for ``autotoken.settings.setup_wizard``."""

from __future__ import annotations

import sys as _sys

from autotoken.settings import setup_wizard as _impl

_sys.modules[__name__] = _impl
