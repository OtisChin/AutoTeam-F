from __future__ import annotations

import importlib
import json
from pathlib import Path

_ENV_NAMES = (
    "OPENAI_SENTINEL_SDK_URL",
    "OPENAI_SENTINEL_VERSION",
    "OPENAI_SENTINEL_SDK_TTL_SECONDS",
)


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected GET")
        return self.responses.pop(0)


def _sentinel_sdk_module():
    return importlib.import_module("autotoken._protocol_register.sentinel_sdk")


def _clear_sdk_env(monkeypatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_resolver_discovers_official_sdk_and_reuses_fresh_cache(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    session = FakeSession([
        FakeResponse(
            200,
            "<html><body><script "
            "src='https://sentinel.openai.com/sentinel/20260830abcd/sdk.js'>"
            "</script></body></html>",
        )
    ])

    discovered = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path,
        now=1_000.0,
    )
    cached = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path,
        now=1_001.0,
    )

    assert discovered.version == "20260830abcd"
    assert discovered.url == (
        "https://sentinel.openai.com/sentinel/20260830abcd/sdk.js"
    )
    assert discovered.source == "discovery"
    assert cached == discovered._replace(source="cache")
    assert [call[0] for call in session.calls] == [sentinel_sdk.SENTINEL_DISCOVERY_URL]


def test_explicit_sdk_url_wins_without_network(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    monkeypatch.setenv(
        "OPENAI_SENTINEL_SDK_URL",
        "https://sentinel.openai.com/sentinel/manual123/sdk.js",
    )
    session = FakeSession([])
    sentinel_sdk = _sentinel_sdk_module()

    resolved = sentinel_sdk.resolve_sentinel_sdk(session, cache_dir=tmp_path)

    assert resolved.version == "manual123"
    assert resolved.url == "https://sentinel.openai.com/sentinel/manual123/sdk.js"
    assert resolved.source == "env_url"
    assert session.calls == []


def test_explicit_version_builds_official_url_without_network(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    monkeypatch.setenv("OPENAI_SENTINEL_VERSION", "20260830cafe")
    session = FakeSession([])
    sentinel_sdk = _sentinel_sdk_module()

    resolved = sentinel_sdk.resolve_sentinel_sdk(session, cache_dir=tmp_path)

    assert resolved.version == "20260830cafe"
    assert resolved.url == (
        "https://sentinel.openai.com/sentinel/20260830cafe/sdk.js"
    )
    assert resolved.source == "env_version"
    assert session.calls == []


def test_stale_last_known_good_is_used_when_discovery_fails(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    monkeypatch.setenv("OPENAI_SENTINEL_SDK_TTL_SECONDS", "60")
    sentinel_sdk = _sentinel_sdk_module()
    cache_file = tmp_path / "latest.json"
    cache_file.write_text(
        json.dumps(
            {
                "version": "20260829beef",
                "sdk_url": (
                    "https://sentinel.openai.com/sentinel/20260829beef/sdk.js"
                ),
                "resolved_at": 1_000.0,
            }
        ),
        encoding="utf-8",
    )
    session = FakeSession([FakeResponse(503, "unavailable")])

    resolved = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path,
        now=2_000.0,
    )

    assert resolved.version == "20260829beef"
    assert resolved.source == "stale_cache"
    assert [call[0] for call in session.calls] == [sentinel_sdk.SENTINEL_DISCOVERY_URL]


def test_untrusted_discovery_url_is_rejected(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    session = FakeSession([
        FakeResponse(
            200,
            "<html><script src='https://attacker.example/sentinel/pwn/sdk.js'>"
            "</script></html>",
        )
    ])

    resolved = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path,
        now=1_000.0,
    )

    assert resolved.version == sentinel_sdk.BUILTIN_SENTINEL_VERSION
    assert resolved.url == sentinel_sdk.BUILTIN_SENTINEL_SDK_URL
    assert resolved.source == "builtin"


def test_builtin_is_used_when_no_cache_and_discovery_is_unavailable(
    tmp_path,
    monkeypatch,
):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    session = FakeSession([FakeResponse(500, "error")])

    resolved = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path,
        now=1_000.0,
    )

    assert resolved.version == sentinel_sdk.BUILTIN_SENTINEL_VERSION
    assert resolved.url == sentinel_sdk.BUILTIN_SENTINEL_SDK_URL
    assert resolved.source == "builtin"


def test_candidates_prefer_primary_then_last_good_then_builtin(
    tmp_path,
    monkeypatch,
):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    last_good = sentinel_sdk.SentinelSdk(
        "20260830good",
        "https://sentinel.openai.com/sentinel/20260830good/sdk.js",
        "discovery",
    )
    primary = sentinel_sdk.SentinelSdk(
        "20260831next",
        "https://sentinel.openai.com/sentinel/20260831next/sdk.js",
        "discovery",
    )

    sentinel_sdk.mark_sentinel_sdk_good(last_good, cache_dir=tmp_path)
    candidates = sentinel_sdk.sentinel_sdk_candidates(
        primary,
        cache_dir=tmp_path,
    )

    assert [(item.version, item.source) for item in candidates] == [
        ("20260831next", "discovery"),
        ("20260830good", "last_good"),
        (sentinel_sdk.BUILTIN_SENTINEL_VERSION, "builtin"),
    ]


def test_candidates_deduplicate_same_sdk_url(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    primary = sentinel_sdk.SentinelSdk(
        sentinel_sdk.BUILTIN_SENTINEL_VERSION,
        sentinel_sdk.BUILTIN_SENTINEL_SDK_URL,
        "env_version",
    )

    sentinel_sdk.mark_sentinel_sdk_good(primary, cache_dir=tmp_path)
    candidates = sentinel_sdk.sentinel_sdk_candidates(
        primary,
        cache_dir=tmp_path,
    )

    assert candidates == (primary,)


def test_unwritable_cache_does_not_hide_successful_discovery(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    session = FakeSession([
        FakeResponse(
            200,
            "<script "
            "src='https://sentinel.openai.com/sentinel/20260830abcd/sdk.js'>"
            "</script>",
        )
    ])
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("cache is read-only")
        ),
    )

    resolved = sentinel_sdk.resolve_sentinel_sdk(
        session,
        cache_dir=tmp_path / "read-only",
        now=1_000.0,
    )

    assert resolved.version == "20260830abcd"
    assert resolved.source == "discovery"


def test_unwritable_cache_does_not_fail_last_good_marking(tmp_path, monkeypatch):
    _clear_sdk_env(monkeypatch)
    sentinel_sdk = _sentinel_sdk_module()
    sdk = sentinel_sdk.SentinelSdk(
        "20260830abcd",
        "https://sentinel.openai.com/sentinel/20260830abcd/sdk.js",
        "discovery",
    )
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("cache is read-only")
        ),
    )

    sentinel_sdk.mark_sentinel_sdk_good(
        sdk,
        cache_dir=tmp_path / "read-only",
    )
