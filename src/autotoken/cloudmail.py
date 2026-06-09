"""Compatibility wrapper for ``autotoken.mail``."""

from __future__ import annotations

import sys as _sys

from autotoken import mail as _impl

_sys.modules[__name__] = _impl
