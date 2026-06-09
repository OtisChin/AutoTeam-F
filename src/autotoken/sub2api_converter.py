"""Compatibility wrapper for ``autotoken.integrations.sub2api_converter``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import sub2api_converter as _impl

_sys.modules[__name__] = _impl
