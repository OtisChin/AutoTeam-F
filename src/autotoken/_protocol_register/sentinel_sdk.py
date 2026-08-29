"""Resolve the current OpenAI Sentinel SDK with cache and safe fallbacks."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

SENTINEL_DISCOVERY_URL = (
    "https://sentinel.openai.com/backend-api/sentinel/frame.html"
)
BUILTIN_SENTINEL_VERSION = "20260219f9f6"
BUILTIN_SENTINEL_SDK_URL = (
    f"https://sentinel.openai.com/sentinel/{BUILTIN_SENTINEL_VERSION}/sdk.js"
)
DEFAULT_SDK_TTL_SECONDS = 6 * 60 * 60

_MAX_DISCOVERY_HTML_BYTES = 1024 * 1024
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
_SDK_PATH_PATTERN = re.compile(r"^/sentinel/([^/]+)/sdk\.js$")
_CACHE_LOCK = threading.Lock()


class SentinelSdk(NamedTuple):
    version: str
    url: str
    source: str


class _ScriptSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.sources.append(value.strip())


def default_sentinel_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "openai-sentinel-demo"


def _version_url(version: str) -> str | None:
    version = str(version or "").strip()
    if not _VERSION_PATTERN.fullmatch(version):
        return None
    return f"https://sentinel.openai.com/sentinel/{version}/sdk.js"


def _validated_sdk_url(url: str) -> tuple[str, str] | None:
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
        path_match = _SDK_PATH_PATTERN.fullmatch(parsed.path)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != "sentinel.openai.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
            or path_match is None
        ):
            return None
    except (TypeError, ValueError):
        return None
    version = path_match.group(1)
    if not _VERSION_PATTERN.fullmatch(version):
        return None
    return version, value


def _ttl_seconds() -> int:
    raw = (os.getenv("OPENAI_SENTINEL_SDK_TTL_SECONDS", "") or "").strip()
    if not raw:
        return DEFAULT_SDK_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "OPENAI_SENTINEL_SDK_TTL_SECONDS 无效，使用默认值 %s",
            DEFAULT_SDK_TTL_SECONDS,
        )
        return DEFAULT_SDK_TTL_SECONDS
    return max(0, value)


def _read_cache(cache_file: Path) -> tuple[SentinelSdk, float] | None:
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        validated = _validated_sdk_url(str(data.get("sdk_url") or ""))
        version = str(data.get("version") or "").strip()
        resolved_at = float(data.get("resolved_at"))
        if validated is None or validated[0] != version:
            return None
        return SentinelSdk(version, validated[1], "cache"), resolved_at
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(cache_file: Path, sdk: SentinelSdk, resolved_at: float) -> None:
    temporary: Path | None = None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_file.parent,
            prefix="latest-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                {
                    "version": sdk.version,
                    "sdk_url": sdk.url,
                    "resolved_at": resolved_at,
                },
                handle,
                separators=(",", ":"),
            )
        os.replace(temporary, cache_file)
    except OSError as exc:
        logger.debug("写入 Sentinel SDK 缓存失败: %s", exc)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str) and text:
        return text[:_MAX_DISCOVERY_HTML_BYTES]
    content = getattr(response, "content", b"") or b""
    if isinstance(content, str):
        return content[:_MAX_DISCOVERY_HTML_BYTES]
    return bytes(content[:_MAX_DISCOVERY_HTML_BYTES]).decode("utf-8", errors="replace")


def _discover_sdk(session: Any, timeout_seconds: int) -> SentinelSdk | None:
    if session is None:
        return None
    response = session.get(
        SENTINEL_DISCOVERY_URL,
        headers={
            "accept": "text/html,application/xhtml+xml",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": "https://auth.openai.com/",
        },
        timeout=max(1, int(timeout_seconds)),
    )
    if getattr(response, "status_code", 0) != 200:
        return None

    parser = _ScriptSourceParser()
    parser.feed(_response_text(response))
    for source in parser.sources:
        validated = _validated_sdk_url(urljoin(SENTINEL_DISCOVERY_URL, source))
        if validated is not None:
            return SentinelSdk(validated[0], validated[1], "discovery")
    return None


def resolve_sentinel_sdk(
    session: Any = None,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    now: float | None = None,
    timeout_seconds: int = 10,
) -> SentinelSdk:
    """Resolve SDK by env override, fresh cache, discovery, stale cache, fallback."""
    explicit_url = (os.getenv("OPENAI_SENTINEL_SDK_URL", "") or "").strip()
    if explicit_url:
        validated = _validated_sdk_url(explicit_url)
        if validated is not None:
            return SentinelSdk(validated[0], validated[1], "env_url")
        logger.warning("忽略非官方或格式无效的 OPENAI_SENTINEL_SDK_URL")

    explicit_version = (os.getenv("OPENAI_SENTINEL_VERSION", "") or "").strip()
    if explicit_version:
        url = _version_url(explicit_version)
        if url is not None:
            return SentinelSdk(explicit_version, url, "env_version")
        logger.warning("忽略格式无效的 OPENAI_SENTINEL_VERSION")

    current_time = time.time() if now is None else float(now)
    root = Path(cache_dir) if cache_dir is not None else default_sentinel_cache_dir()
    cache_file = root / "latest.json"

    with _CACHE_LOCK:
        cached = _read_cache(cache_file)
        if cached is not None and current_time - cached[1] <= _ttl_seconds():
            return cached[0]

        try:
            discovered = _discover_sdk(session, timeout_seconds)
        except Exception as exc:
            logger.debug("发现 Sentinel SDK 失败: %s", exc)
            discovered = None
        if discovered is not None:
            _write_cache(cache_file, discovered, current_time)
            return discovered

        if cached is not None:
            return cached[0]._replace(source="stale_cache")

    return SentinelSdk(
        BUILTIN_SENTINEL_VERSION,
        BUILTIN_SENTINEL_SDK_URL,
        "builtin",
    )


def mark_sentinel_sdk_good(
    sdk: SentinelSdk,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> None:
    """Persist an SDK only after a complete QuickJS solve succeeds."""
    validated = _validated_sdk_url(sdk.url)
    if validated is None or validated[0] != sdk.version:
        logger.warning("忽略格式无效的 Sentinel last-known-good SDK")
        return
    root = Path(cache_dir) if cache_dir is not None else default_sentinel_cache_dir()
    with _CACHE_LOCK:
        _write_cache(root / "last-good.json", sdk, time.time())


def sentinel_sdk_candidates(
    primary: SentinelSdk,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> tuple[SentinelSdk, ...]:
    """Return primary, runtime-validated last-good, then built-in SDK."""
    root = Path(cache_dir) if cache_dir is not None else default_sentinel_cache_dir()
    with _CACHE_LOCK:
        cached = _read_cache(root / "last-good.json")

    candidates = [primary]
    if cached is not None:
        candidates.append(cached[0]._replace(source="last_good"))
    candidates.append(
        SentinelSdk(
            BUILTIN_SENTINEL_VERSION,
            BUILTIN_SENTINEL_SDK_URL,
            "builtin",
        )
    )

    unique: list[SentinelSdk] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        unique.append(candidate)
    return tuple(unique)
