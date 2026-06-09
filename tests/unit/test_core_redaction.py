from autotoken.core.redaction import (
    compact_log_text,
    safe_email_summary,
    safe_error_summary,
    safe_otp_summary,
    safe_proxy_summary,
    safe_url_summary,
)


def test_safe_url_summary_redacts_tokens_and_uuid_segments():
    value = safe_url_summary(
        "https://example.test/pay/123e4567-e89b-12d3-a456-426614174000?token=secret-token&locale=en"
    )

    assert "secret-token" not in value
    assert "123e4567-e89b-12d3-a456-426614174000" not in value
    assert "locale=en" in value


def test_safe_proxy_summary_redacts_proxy_password():
    value = safe_proxy_summary("http://proxy-user:secret-pass@127.0.0.1:8080")

    assert "secret-pass" not in value
    assert "password_present=True" in value
    assert "host=127.0.0.1" in value


def test_safe_email_and_otp_summary_mask_sensitive_parts():
    assert safe_email_summary("longlocalpart@example.com").endswith("@example.com")
    assert "longlocalpart" not in safe_email_summary("longlocalpart@example.com")
    assert "123456" not in safe_otp_summary("123456")


def test_safe_error_summary_redacts_bearer_and_query_secret():
    value = safe_error_summary("GET /x?access_token=abc123 failed with Bearer secret.jwt.token")

    assert "abc123" not in value
    assert "secret.jwt.token" not in value
    assert "<redacted>" in value


def test_compact_log_text_collapses_whitespace_and_truncates():
    assert compact_log_text("a\n\n b\t c", limit=20) == "a b c"
    assert compact_log_text("x" * 20, limit=8) == "xxxxxxxx..."
