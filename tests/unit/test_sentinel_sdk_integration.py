from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from autotoken._protocol_register import sentinel, sentinel_quickjs
from autotoken._protocol_register.sentinel_sdk import SentinelSdk

DYNAMIC_VERSION = "20260830feed"
DYNAMIC_URL = f"https://sentinel.openai.com/sentinel/{DYNAMIC_VERSION}/sdk.js"
DYNAMIC_SDK = SentinelSdk(DYNAMIC_VERSION, DYNAMIC_URL, "discovery")

_OLD_LAYOUT_SDK = """
var SentinelSDK=function(t){
class _{async getRequirementsToken(){return "requirements-old"}async getEnforcementToken(){return "final-old"}}
var P=new _;
const I=new WeakMap;function D(t,n){I.set(t,n)}function $(t){return I.get(t)}
async function _n(t,n){return $(t)+":"+n}
async function ye(t){const e={turnstile:{dx:"dx"}};return e.turnstile.dx?await _n(e,e.turnstile.dx):null}
return t.init=function(){},t.token=ye,t}({});
"""

_CURRENT_LAYOUT_SDK = """
var SentinelSDK=function(t){
class O{async getRequirementsToken(){return "requirements-current"}async getEnforcementToken(){return "final-current"}}
var E=new O;
function j(){const t=["get","set"];return(j=function(){return t})()}
const U=new WeakMap;function I(t,n){const e=j();return(I=function(t,n){return e[t-=0]})(t,n)}
function D(t,n){U[I(1)](t,n)}function F(t){return U[I(0)](t)}
async function Rn(t,n){return F(t)+":"+n}
async function je(t){const e={turnstile:{dx:"dx"}};return e.turnstile.dx?await Rn(e,e.turnstile.dx):null}
return t.timing=function(){return null},t.token=je,t}({});
"""


class SdkResponse:
    status_code = 200
    content = b"var SentinelSDK={};"
    text = content.decode("utf-8")


class DownloadSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return SdkResponse()


class SlowDownloadSession(DownloadSession):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def get(self, url: str, **kwargs):
        with self._lock:
            self.calls.append((url, kwargs))
        time.sleep(0.05)
        return SdkResponse()


def test_quickjs_download_uses_resolved_sdk_url_and_version_cache(
    tmp_path,
    monkeypatch,
):
    session = DownloadSession()
    monkeypatch.setattr(sentinel_quickjs.tempfile, "gettempdir", lambda: str(tmp_path))

    sdk_file = sentinel_quickjs._ensure_sdk_file(
        session,
        timeout_ms=20_000,
        sdk=DYNAMIC_SDK,
    )

    assert session.calls[0][0] == DYNAMIC_URL
    assert sdk_file == (
        Path(tmp_path)
        / "openai-sentinel-demo"
        / DYNAMIC_VERSION
        / "sdk.js"
    )
    assert sdk_file.read_bytes() == SdkResponse.content


def test_concurrent_quickjs_sdk_download_is_coalesced(tmp_path, monkeypatch):
    session = SlowDownloadSession()
    monkeypatch.setattr(sentinel_quickjs.tempfile, "gettempdir", lambda: str(tmp_path))

    def ensure_file(_index: int):
        return sentinel_quickjs._ensure_sdk_file(
            session,
            timeout_ms=20_000,
            sdk=DYNAMIC_SDK,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        files = list(executor.map(ensure_file, range(8)))

    assert len(session.calls) == 1
    assert len(set(files)) == 1
    assert files[0].read_bytes() == SdkResponse.content


def test_quickjs_flow_passes_same_resolved_sdk_to_vm_and_challenge(
    tmp_path,
    monkeypatch,
):
    actions: list[tuple[str, dict]] = []
    challenge_sdks: list[SentinelSdk] = []
    ensured_sdks: list[SentinelSdk] = []
    sdk_file = tmp_path / "sdk.js"
    sdk_file.write_text("sdk", encoding="utf-8")

    monkeypatch.setattr(
        sentinel_quickjs,
        "resolve_sentinel_sdk",
        lambda _session, **_kwargs: DYNAMIC_SDK,
    )

    def fake_ensure(_session, _timeout_ms, *, sdk):
        ensured_sdks.append(sdk)
        return sdk_file

    def fake_action(*, action, payload, **_kwargs):
        actions.append((action, payload))
        if action == "requirements":
            return {"request_p": "requirements-p"}
        return {"final_p": "final-p", "t": "turnstile-token"}

    def fake_challenge(_session, *, sdk, **_kwargs):
        challenge_sdks.append(sdk)
        return {"token": "challenge-token"}

    monkeypatch.setattr(sentinel_quickjs, "_ensure_sdk_file", fake_ensure)
    monkeypatch.setattr(sentinel_quickjs, "_run_quickjs_action", fake_action)
    monkeypatch.setattr(sentinel_quickjs, "_fetch_sentinel_challenge", fake_challenge)

    token = sentinel_quickjs.get_sentinel_token_via_quickjs(
        object(),
        device_id="did-123",
    )

    assert json.loads(token or "{}") == {
        "p": "final-p",
        "t": "turnstile-token",
        "c": "challenge-token",
        "id": "did-123",
        "flow": "authorize_continue",
    }
    assert ensured_sdks == [DYNAMIC_SDK]
    assert challenge_sdks == [DYNAMIC_SDK]
    assert [payload["sdk_url"] for _, payload in actions] == [
        DYNAMIC_URL,
        DYNAMIC_URL,
    ]


def test_python_generator_uses_supplied_sdk_url_in_fingerprint():
    generator = sentinel.SentinelTokenGenerator(
        device_id="did-123",
        sdk_url=DYNAMIC_URL,
    )

    assert generator._get_config()[5] == DYNAMIC_URL


def test_python_fallback_resolves_sdk_once_for_challenge_and_pow(monkeypatch):
    captured_sdk_urls: list[str] = []
    monkeypatch.setattr(
        sentinel,
        "resolve_sentinel_sdk",
        lambda _session, **_kwargs: DYNAMIC_SDK,
    )

    def fake_challenge(_session, _device_id, *, sdk_url, **_kwargs):
        captured_sdk_urls.append(sdk_url)
        return {"token": "challenge-token", "proofofwork": {"required": False}}

    monkeypatch.setattr(sentinel, "fetch_sentinel_challenge", fake_challenge)

    token = sentinel.build_sentinel_token(object(), "did-123")

    parsed = json.loads(token or "{}")
    config = json.loads(base64.b64decode(parsed["p"][7:]).decode("utf-8"))
    assert captured_sdk_urls == [DYNAMIC_URL]
    assert config[5] == DYNAMIC_URL


def test_quickjs_runtime_exposes_resolved_sdk_as_current_script():
    source = sentinel_quickjs._quickjs_script_path().read_text(encoding="utf-8")

    assert "currentScript: { src: String(payload.sdk_url" in source


def test_quickjs_semantic_patcher_supports_old_and_current_minified_layouts(
    tmp_path,
):
    for name, source, suffix in (
        ("old", _OLD_LAYOUT_SDK, "old"),
        ("current", _CURRENT_LAYOUT_SDK, "current"),
    ):
        sdk_file = tmp_path / f"{name}.js"
        sdk_file.write_text(source, encoding="utf-8")
        requirements = sentinel_quickjs._run_quickjs_action(
            action="requirements",
            sdk_file=sdk_file,
            quickjs_script=sentinel_quickjs._quickjs_script_path(),
            payload={"device_id": "did-123", "sdk_url": DYNAMIC_URL},
            timeout_ms=20_000,
        )
        solved = sentinel_quickjs._run_quickjs_action(
            action="solve",
            sdk_file=sdk_file,
            quickjs_script=sentinel_quickjs._quickjs_script_path(),
            payload={
                "device_id": "did-123",
                "sdk_url": DYNAMIC_URL,
                "request_p": f"requirements-{suffix}",
                "challenge": {"turnstile": {"dx": "dx"}},
            },
            timeout_ms=20_000,
        )

        assert requirements == {"request_p": f"requirements-{suffix}"}
        assert solved == {
            "final_p": f"final-{suffix}",
            "t": f"requirements-{suffix}:dx",
        }


def test_quickjs_falls_back_to_last_good_sdk_and_marks_success(
    tmp_path,
    monkeypatch,
):
    future_sdk = SentinelSdk(
        "20260831next",
        "https://sentinel.openai.com/sentinel/20260831next/sdk.js",
        "discovery",
    )
    good_sdk = SentinelSdk(
        "20260830good",
        "https://sentinel.openai.com/sentinel/20260830good/sdk.js",
        "last_good",
    )
    attempted: list[SentinelSdk] = []
    marked: list[SentinelSdk] = []
    logs: list[str] = []

    monkeypatch.setattr(
        sentinel_quickjs,
        "resolve_sentinel_sdk",
        lambda _session, **_kwargs: future_sdk,
    )
    monkeypatch.setattr(
        sentinel_quickjs,
        "sentinel_sdk_candidates",
        lambda sdk: (sdk, good_sdk),
    )
    monkeypatch.setattr(
        sentinel_quickjs,
        "mark_sentinel_sdk_good",
        marked.append,
    )

    def fake_ensure(_session, _timeout_ms, *, sdk):
        attempted.append(sdk)
        path = tmp_path / f"{sdk.version}.js"
        path.write_text("sdk", encoding="utf-8")
        return path

    def fake_action(*, sdk_file, action, **_kwargs):
        if sdk_file.stem == future_sdk.version:
            raise RuntimeError("unsupported Sentinel SDK")
        if action == "requirements":
            return {"request_p": "requirements-good"}
        return {"final_p": "final-good", "t": "turnstile-good"}

    monkeypatch.setattr(sentinel_quickjs, "_ensure_sdk_file", fake_ensure)
    monkeypatch.setattr(sentinel_quickjs, "_run_quickjs_action", fake_action)
    monkeypatch.setattr(
        sentinel_quickjs,
        "_fetch_sentinel_challenge",
        lambda _session, **_kwargs: {"token": "challenge-good"},
    )

    token = sentinel_quickjs.get_sentinel_token_via_quickjs(
        object(),
        device_id="did-123",
        log=logs.append,
    )

    assert json.loads(token or "{}") == {
        "p": "final-good",
        "t": "turnstile-good",
        "c": "challenge-good",
        "id": "did-123",
        "flow": "authorize_continue",
    }
    assert attempted == [future_sdk, good_sdk]
    assert marked == [good_sdk]
    assert any(future_sdk.version in message for message in logs)


def test_quickjs_does_not_retry_sdk_when_challenge_transport_fails(
    tmp_path,
    monkeypatch,
):
    future_sdk = SentinelSdk(
        "20260831next",
        "https://sentinel.openai.com/sentinel/20260831next/sdk.js",
        "discovery",
    )
    good_sdk = SentinelSdk(
        "20260830good",
        "https://sentinel.openai.com/sentinel/20260830good/sdk.js",
        "last_good",
    )
    attempted: list[SentinelSdk] = []

    monkeypatch.setattr(
        sentinel_quickjs,
        "resolve_sentinel_sdk",
        lambda _session, **_kwargs: future_sdk,
    )
    monkeypatch.setattr(
        sentinel_quickjs,
        "sentinel_sdk_candidates",
        lambda sdk: (sdk, good_sdk),
    )

    def fake_ensure(_session, _timeout_ms, *, sdk):
        attempted.append(sdk)
        path = tmp_path / f"{sdk.version}.js"
        path.write_text("sdk", encoding="utf-8")
        return path

    monkeypatch.setattr(sentinel_quickjs, "_ensure_sdk_file", fake_ensure)
    monkeypatch.setattr(
        sentinel_quickjs,
        "_run_quickjs_action",
        lambda **_kwargs: {"request_p": "requirements-p"},
    )
    monkeypatch.setattr(
        sentinel_quickjs,
        "_fetch_sentinel_challenge",
        lambda _session, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("challenge HTTP 503")
        ),
    )

    token = sentinel_quickjs.get_sentinel_token_via_quickjs(
        object(),
        device_id="did-123",
        log=lambda _message: None,
    )

    assert token is None
    assert attempted == [future_sdk]
