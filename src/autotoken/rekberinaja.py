"""Compatibility wrapper for ``autotoken.integrations.rekberinaja``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import rekberinaja as _impl

_sys.modules[__name__] = _impl
