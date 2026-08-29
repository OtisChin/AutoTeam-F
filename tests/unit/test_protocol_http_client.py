from autotoken._protocol_register import http_client


def test_protocol_retry_policy_excludes_state_changing_methods():
    policy = http_client.build_safe_retry_policy()

    assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
    assert "POST" not in policy.allowed_methods


def test_user_agent_matches_configured_chrome_profile():
    assert "Chrome/136.0.0.0" in http_client.user_agent_for_impersonate("chrome136")


def test_requests_fallback_uses_configured_profile_user_agent(monkeypatch):
    monkeypatch.setattr(http_client, "_HAS_CFFI", False)

    session = http_client.create_http_session(impersonate="chrome141")
    try:
        assert "Chrome/141.0.0.0" in session.headers["User-Agent"]
    finally:
        session.close()
