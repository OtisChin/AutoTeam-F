"""Compatibility wrapper for ``autotoken.integrations.cpa_sync``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import cpa_sync as _impl

_sys.modules[__name__] = _impl
