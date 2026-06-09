"""Compatibility wrapper for ``autotoken.integrations.account_hub``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import account_hub as _impl

_sys.modules[__name__] = _impl
