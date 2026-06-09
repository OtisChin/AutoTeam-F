"""Compatibility wrapper for ``autotoken.auth.protocol_register``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import protocol_register as _impl

_sys.modules[__name__] = _impl
