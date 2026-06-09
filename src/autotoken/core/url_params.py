"""Small URL query/fragment parameter helpers."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def first_url_param(
    url: str,
    *names: str,
    include_query: bool = True,
    include_fragment: bool = True,
    keep_blank_values: bool = True,
) -> str:
    parsed = urlparse(str(url or ""))
    sources = []
    if include_query:
        sources.append(parse_qs(parsed.query or "", keep_blank_values=keep_blank_values))
    if include_fragment:
        sources.append(parse_qs(parsed.fragment or "", keep_blank_values=keep_blank_values))
    for name in names:
        for values in sources:
            value = str((values.get(name) or [""])[0] or "").strip()
            if value:
                return value
    return ""


def has_url_param(url: str, *names: str, include_query: bool = True, include_fragment: bool = True) -> bool:
    return bool(
        first_url_param(
            url,
            *names,
            include_query=include_query,
            include_fragment=include_fragment,
            keep_blank_values=False,
        )
    )
