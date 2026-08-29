from autotoken._protocol_register import http_client


def test_protocol_retry_policy_excludes_state_changing_methods():
    policy = http_client.build_safe_retry_policy()

    assert policy.allowed_methods == frozenset({"GET", "HEAD", "OPTIONS"})
    assert "POST" not in policy.allowed_methods
