from types import SimpleNamespace

from autotoken import api
from autotoken.services import api_helpers


class FakeRequest:
    def __init__(self, headers=None, scheme="http", base_url="http://local.test/"):
        self.headers = headers or {}
        self.url = SimpleNamespace(scheme=scheme)
        self.base_url = base_url


class BrokenRequest:
    @property
    def headers(self):
        raise RuntimeError("broken request")


def test_request_public_base_url_uses_env_for_missing_or_broken_request(monkeypatch):
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", " https://public.example.com/base/ ")

    assert api_helpers.request_public_base_url(None) == "https://public.example.com/base"
    assert api_helpers.request_public_base_url(BrokenRequest()) == "https://public.example.com/base"


def test_request_public_base_url_prefers_forwarded_headers():
    request = FakeRequest(
        headers={
            "x-forwarded-host": " public.example.com, proxy.internal ",
            "x-forwarded-proto": " https, http ",
            "host": "ignored.local",
        },
        scheme="http",
        base_url="http://ignored.local/",
    )

    assert api_helpers.request_public_base_url(request) == "https://public.example.com"


def test_request_public_base_url_falls_back_to_host_or_base_url():
    assert api_helpers.request_public_base_url(FakeRequest(headers={"host": "api.example.com"}, scheme="https")) == (
        "https://api.example.com"
    )
    assert api_helpers.request_public_base_url(FakeRequest(headers={}, base_url=" http://local.test/root/ ")) == (
        "http://local.test/root"
    )


def test_safe_url_for_log_summarizes_host_and_truncates_path():
    assert api_helpers.safe_url_for_log(" https://example.com/a/b?secret=1 ") == "host=example.com path=/a/b"

    long_path = "/" + ("a" * 45)
    assert api_helpers.safe_url_for_log(f"https://example.com{long_path}") == (
        f"host=example.com path={long_path[:40]}..."
    )


def test_mask_secret_for_config_preserves_existing_redaction_shape():
    assert api_helpers.mask_secret_for_config("") == ""
    assert api_helpers.mask_secret_for_config("abc") == "******"
    assert api_helpers.mask_secret_for_config("abcde") == "ab******de"
    assert api_helpers.mask_secret_for_config("abcd1234") == "ab******34"
    assert api_helpers.mask_secret_for_config("abcd1234efgh") == "abcd******efgh"


def test_api_keeps_compatibility_wrappers_for_api_helpers(monkeypatch):
    monkeypatch.setenv("AUTOTOKEN_LOCAL_BASE_URL", "https://public.example.com/")

    assert api._request_public_base_url(None) == "https://public.example.com"
    assert api._safe_url_for_log("https://example.com/demo") == "host=example.com path=/demo"
    assert api._mask_secret_for_config("abcd1234efgh") == "abcd******efgh"
