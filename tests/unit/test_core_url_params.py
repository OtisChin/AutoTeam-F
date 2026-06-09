from autotoken.core.url_params import first_url_param, has_url_param


def test_first_url_param_prefers_query_before_fragment_and_name_order():
    url = "https://example.test/callback?code=query-code#code=fragment-code&state=fragment-state"

    assert first_url_param(url, "code") == "query-code"
    assert first_url_param(url, "state") == "fragment-state"
    assert first_url_param(url, "missing", "state") == "fragment-state"


def test_first_url_param_can_ignore_fragment_values():
    url = "https://example.test/callback#code=fragment-code"

    assert first_url_param(url, "code", include_fragment=False) == ""
    assert has_url_param(url, "code") is True
    assert has_url_param(url, "missing") is False
