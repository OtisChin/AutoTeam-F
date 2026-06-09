from urllib.parse import parse_qs, urlsplit

from autotoken.core.oauth_helper import oauth_helper_auth_url, oauth_helper_fragment


def test_oauth_helper_fragment_prefers_autotoken_and_keeps_legacy_aliases():
    values = parse_qs(oauth_helper_fragment("secret-token", 4711, "https://auth.example/authorize"))

    assert values["autotoken_token"] == ["secret-token"]
    assert values["autotoken_port"] == ["4711"]
    assert values["autotoken_auth"] == ["https://auth.example/authorize"]
    assert values["autoteam_token"] == ["secret-token"]
    assert values["autoteam_port"] == ["4711"]
    assert values["autoteam_auth"] == ["https://auth.example/authorize"]


def test_oauth_helper_auth_url_can_emit_canonical_only_fragment():
    fragment = urlsplit(
        oauth_helper_auth_url(
            "secret-token",
            4711,
            "https://auth.example/authorize",
            include_legacy_aliases=False,
        )
    ).fragment
    values = parse_qs(fragment)

    assert values == {
        "autotoken_token": ["secret-token"],
        "autotoken_port": ["4711"],
        "autotoken_auth": ["https://auth.example/authorize"],
    }
