"""Small HTTP API helper functions with no FastAPI dependency."""

import os
from typing import Any
from urllib.parse import urlsplit


def local_public_base_url() -> str:
    return str(os.environ.get("AUTOTOKEN_LOCAL_BASE_URL") or "").strip().rstrip("/")


def request_public_base_url(request: Any | None) -> str:
    if request is None:
        return local_public_base_url()
    try:
        forwarded_host = str(request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
        forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
        host = forwarded_host or str(request.headers.get("host") or "").strip()
        if host:
            scheme = forwarded_proto or str(request.url.scheme or "http")
            return f"{scheme}://{host}".rstrip("/")
        return str(request.base_url).strip().rstrip("/")
    except Exception:
        return local_public_base_url()


def safe_url_for_log(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        host = parts.netloc or parts.path.split("/", 1)[0]
        path = parts.path or ""
        return f"host={host} path={path[:40]}{'...' if len(path) > 40 else ''}"
    except Exception:
        return text[:80]


def mask_secret_for_config(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return f"{text[:2]}******{text[-2:]}" if len(text) > 4 else "******"
    return f"{text[:4]}******{text[-4:]}"
