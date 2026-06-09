import pytest

from autotoken.core.env import read_env_lines, set_env_default_with_legacy_alias


def test_set_env_default_with_legacy_alias_prefers_runtime_canonical_value():
    environ = {"AUTOTOKEN_DB_FILE": "runtime.sqlite3", "AUTOTEAM_DB_FILE": "legacy.sqlite3"}

    set_env_default_with_legacy_alias("AUTOTOKEN_DB_FILE", "default.sqlite3", environ)

    assert environ["AUTOTOKEN_DB_FILE"] == "runtime.sqlite3"


def test_read_env_lines_returns_empty_for_missing_file(tmp_path):
    assert read_env_lines(tmp_path / ".env") == []


def test_read_env_lines_rejects_oversized_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ABCDEF", encoding="utf-8")

    with pytest.raises(ValueError, match=".env 文件过大"):
        read_env_lines(env_file, max_bytes=5)


def test_read_env_lines_reads_normal_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=2\n", encoding="utf-8")

    assert read_env_lines(env_file) == ["A=1", "B=2"]
