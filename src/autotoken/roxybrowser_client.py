"""Compatibility wrapper for ``autotoken.integrations.roxybrowser_client``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import roxybrowser_client as _impl

_sys.modules[__name__] = _impl
