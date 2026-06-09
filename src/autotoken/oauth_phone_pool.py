"""Compatibility wrapper for ``autotoken.auth.oauth_phone_pool``."""

from __future__ import annotations

import sys as _sys

from autotoken.auth import oauth_phone_pool as _impl

_sys.modules[__name__] = _impl
