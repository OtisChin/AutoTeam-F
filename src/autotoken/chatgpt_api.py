"""Compatibility wrapper for ``autotoken.integrations.chatgpt_api``."""

from __future__ import annotations

import sys as _sys

from autotoken.integrations import chatgpt_api as _impl

_sys.modules[__name__] = _impl
