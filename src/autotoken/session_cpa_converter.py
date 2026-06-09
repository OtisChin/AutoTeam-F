"""Compatibility wrapper for ``autotoken.integrations.session_cpa_converter``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import session_cpa_converter as _impl

_sys.modules[__name__] = _impl
