from __future__ import annotations

import sys
from pathlib import Path

import httpx

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "src" / "autotoken" / "_paypal_protocol_engine"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from paypal.flow import PayPalFlow  # noqa: E402
from paypal.models import SessionState  # noqa: E402


class _Phase0Response:
    status_code = 200
    headers: dict[str, str] = {}
    text = '<html><script>window.__INITIAL_DATA__ = {"ctxId":"CTX-TH"}</script>?ssrt=123456</html>'

    def __init__(self, url: str):
        self.url = url


class _TimeoutThenSuccessSession:
    def __init__(self):
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self.fallback_reasons: list[str] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append((url, kwargs))
        if len(self.get_calls) == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        return _Phase0Response(url)

    def retry_without_http2(self, reason: str = "") -> bool:
        self.fallback_reasons.append(reason)
        return True


def test_phase0_initial_load_retries_once_without_http2_after_read_timeout(monkeypatch):
    flow = PayPalFlow.__new__(PayPalFlow)
    flow.ba_token = "BA-1TH123"
    flow.state = SessionState(ba_token=flow.ba_token)
    flow.session = _TimeoutThenSuccessSession()
    flow._datadome_browser_document = {}
    flow._last_modxo_html = ""
    flow._last_modxo_base_url = ""

    monkeypatch.setattr(flow, "_datadome_mode", lambda: "auto")
    monkeypatch.setattr(flow, "_datadome_phase0_preflight_enabled", lambda: False)
    monkeypatch.setattr(flow, "_capture_datadome_clientid", lambda _html: None)
    monkeypatch.setattr(flow, "_capture_mtr_metadata", lambda _html, _url: None)
    monkeypatch.setattr(flow, "_apply_modxo_inline_metadata", lambda _html: None)
    monkeypatch.setattr(flow, "_extract_modxo_action_ids", lambda _html, _url: None)

    flow._phase0_initial_load()

    assert len(flow.session.get_calls) == 2
    assert flow.session.get_calls[0][0] == flow.session.get_calls[1][0]
    assert flow.session.fallback_reasons
    assert "phase0" in flow.session.fallback_reasons[0]
    assert flow.state.ssrt == "123456"
