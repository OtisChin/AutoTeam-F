"""Compatibility wrapper for ``autotoken.storage.sqlite_store``."""

from __future__ import annotations

import sys as _sys

from autotoken.storage import sqlite_store as _impl

_sys.modules[__name__] = _impl
