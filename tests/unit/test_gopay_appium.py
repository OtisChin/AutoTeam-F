from types import SimpleNamespace

from autotoken.payments import gopay_appium


def test_ldconsole_command_args_preserve_executable_path_and_split_args() -> None:
    args = gopay_appium.GopayAppiumDriver._ldconsole_command_args(
        r"C:\Program Files\LDPlayer9\ldconsole.exe",
        "modify",
        '--index 3 --name "GoPay Test"',
    )

    assert args == [
        r"C:\Program Files\LDPlayer9\ldconsole.exe",
        "modify",
        "--index",
        "3",
        "--name",
        "GoPay Test",
    ]


def test_run_ldconsole_executes_argv_without_shell(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="ok", stderr="warn")

    monkeypatch.setattr(gopay_appium.subprocess, "run", fake_run)
    driver = object.__new__(gopay_appium.GopayAppiumDriver)
    driver._ldconsole_path = r"C:\Program Files\LDPlayer9\ldconsole.exe"

    output = driver._run_ldconsole("launch", "--index 3")

    assert output == "okwarn"
    assert calls == [
        (
            [r"C:\Program Files\LDPlayer9\ldconsole.exe", "launch", "--index", "3"],
            {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 30,
            },
        )
    ]
