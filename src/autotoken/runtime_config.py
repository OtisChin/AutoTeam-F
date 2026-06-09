"""Compatibility wrapper for ``autotoken.settings.runtime_config``."""

from __future__ import annotations

import sys as _sys

from autotoken.settings import runtime_config as _impl

_sys.modules[__name__] = _impl
