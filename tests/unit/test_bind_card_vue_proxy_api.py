from pathlib import Path

BIND_CARD_VUE = Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "BindCard.vue"


def test_auto_bind_proxy_api_selector_includes_711proxy():
    source = BIND_CARD_VUE.read_text(encoding="utf-8")

    assert '<option value="711proxy">711Proxy</option>' in source
    assert "proxy_api_provider: bindTaskForm.value.proxyApiEnabled ? bindTaskForm.value.proxyApiProvider : ''" in source
    assert "['1024proxy', 'cliproxy', '711proxy']" in source


def test_generate_link_proxy_api_selector_is_sent_to_backend():
    source = BIND_CARD_VUE.read_text(encoding="utf-8")

    assert 'v-model="bindForm.proxyApiEnabled"' in source
    assert 'v-model="bindForm.proxyApiProvider"' in source
    assert 'v-model="bindForm.proxyApiCountry"' in source
    assert "proxy_api_enabled: Boolean(bindForm.value.proxyApiEnabled)" in source
    assert "proxy_api_provider: bindForm.value.proxyApiEnabled ? bindForm.value.proxyApiProvider : ''" in source


def test_proxy_api_url_inputs_are_removed_from_bind_card_page():
    source = BIND_CARD_VUE.read_text(encoding="utf-8")

    assert "代理 API URL（可选）" not in source
    assert 'v-model.trim="bindForm.proxyApiUrl"' not in source
    assert 'v-model.trim="bindTaskForm.proxyApiUrl"' not in source
    assert "proxy_api_url: bindForm.value.proxyApiEnabled ? String(bindForm.value.proxyApiUrl || '').trim() : ''" not in source
    assert (
        "proxy_api_url: bindTaskForm.value.proxyApiEnabled ? String(bindTaskForm.value.proxyApiUrl || '').trim() : ''"
        not in source
    )


def test_generate_link_proxy_api_defaults_disabled():
    source = BIND_CARD_VUE.read_text(encoding="utf-8")

    assert "const bindForm = ref({" in source
    bind_form_start = source.index("const bindForm = ref({")
    bind_form_end = source.index("})", bind_form_start)
    bind_form_source = source[bind_form_start:bind_form_end]
    assert "proxyApiEnabled: false" in bind_form_source
