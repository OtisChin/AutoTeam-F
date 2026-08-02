from pathlib import Path

BIND_CARD_VUE = Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "BindCard.vue"


def test_auto_bind_proxy_api_selector_includes_711proxy():
    source = BIND_CARD_VUE.read_text(encoding="utf-8")

    assert '<option value="711proxy">711Proxy</option>' in source
    assert "proxy_api_provider: bindTaskForm.value.proxyApiEnabled ? bindTaskForm.value.proxyApiProvider : ''" in source
    assert "['1024proxy', 'cliproxy', '711proxy']" in source
