"""OAuth helper URL construction shared by browser-based login flows."""

from __future__ import annotations

from urllib.parse import urlencode

OAUTH_HELPER_AUTH_URL = "https://auth.openai.com/"


def oauth_helper_fragment(token: str, port: str | int, auth_url: str, *, include_legacy_aliases: bool = True) -> str:
    values = {
        "autotoken_token": str(token or ""),
        "autotoken_port": str(port or ""),
        "autotoken_auth": str(auth_url or ""),
    }
    if include_legacy_aliases:
        values.update(
            {
                "autoteam_token": values["autotoken_token"],
                "autoteam_port": values["autotoken_port"],
                "autoteam_auth": values["autotoken_auth"],
            }
        )
    return urlencode(values)


def oauth_helper_auth_url(token: str, port: str | int, auth_url: str, *, include_legacy_aliases: bool = True) -> str:
    return f"{OAUTH_HELPER_AUTH_URL}#{oauth_helper_fragment(token, port, auth_url, include_legacy_aliases=include_legacy_aliases)}"
