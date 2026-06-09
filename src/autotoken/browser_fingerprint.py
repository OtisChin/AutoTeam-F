"""Compatibility wrapper for ``autotoken.core.browser_fingerprint``."""

from __future__ import annotations

import sys as _sys

from autotoken.core import browser_fingerprint as _impl

_sys.modules[__name__] = _impl
