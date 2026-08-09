import pytest

from autotoken.services.totp import (
    TOTPSecretError,
    generate_totp,
    generate_totp_candidates,
    mask_totp_secret,
    normalize_totp_secret,
    parse_otpauth_uri,
)

RFC6238_BASE32 = ("GEZDGNBVGY3TQOJQ" + "GEZDGNBVGY3TQOJQ")


def test_generate_totp_uses_rfc6238_sha1_six_digits():
    assert generate_totp(RFC6238_BASE32, for_time=59) == "287082"


def test_normalize_secret_accepts_lowercase_and_spaces():
    assert normalize_totp_secret(" gezd gnbv gy3tqojq ") == "GEZDGNBVGY3TQOJQ"


def test_normalize_secret_rejects_invalid_base32_characters():
    with pytest.raises(TOTPSecretError, match="invalid base32"):
        normalize_totp_secret("ABCDEF10")


def test_parse_otpauth_uri_extracts_openai_totp_metadata():
    metadata = parse_otpauth_uri(
        "otpauth://totp/OpenAI:user%40example.com?secret=abcd%20efgh&issuer=OpenAI"
    )

    assert metadata.secret == "ABCDEFGH"
    assert metadata.issuer == "OpenAI"
    assert metadata.label == "OpenAI:user@example.com"
    assert metadata.account_name == "user@example.com"


def test_generate_totp_candidates_returns_previous_current_next_windows():
    candidates = generate_totp_candidates(RFC6238_BASE32, for_time=60)

    assert candidates == [
        generate_totp(RFC6238_BASE32, for_time=30),
        generate_totp(RFC6238_BASE32, for_time=60),
        generate_totp(RFC6238_BASE32, for_time=90),
    ]
    assert len(set(candidates)) == 3


def test_mask_totp_secret_does_not_expose_raw_secret():
    masked = mask_totp_secret("ABCDEFGH234567AB")

    assert masked == "ABCD…67AB"
    assert "ABCDEFGH234567AB" not in masked


