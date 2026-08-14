from paypal.proxy import ProxyEntry


def test_raw_proxy_line_defaults_to_socks5h_for_arxlabs_style_pool():
    entry = ProxyEntry.parse("us.arxlabs.io:3010:user-region-TH-sid-demo-t-120:pass")

    assert entry.scheme == "socks5h"
    assert entry.url.startswith("socks5h://")


def test_explicit_proxy_url_keeps_declared_scheme():
    entry = ProxyEntry.parse("http://user:pass@us.arxlabs.io:3010")

    assert entry.scheme == "http"
    assert entry.url.startswith("http://")
