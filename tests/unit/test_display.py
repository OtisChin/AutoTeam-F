import subprocess

from autotoken.core import display


def test_start_xvfb_process_fallback_uses_argv_without_shell(monkeypatch):
    calls = []
    monkeypatch.delenv("DISPLAY", raising=False)

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(display.subprocess, "Popen", fake_popen)

    display._start_xvfb_process_fallback()

    assert calls == [
        (
            ["Xvfb", ":99", "-screen", "0", "1280x800x24"],
            {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "start_new_session": True,
            },
        )
    ]
