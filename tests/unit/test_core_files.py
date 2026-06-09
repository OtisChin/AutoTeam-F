import pytest

from autotoken.core.files import (
    READ_JSON_FILE_MAX_BYTES,
    READ_LINES_FILE_MAX_BYTES,
    append_unique_non_comment_lines,
    read_json_file,
    read_lines_file,
    write_json_atomic,
)


def test_read_json_file_returns_fallback_for_missing_or_invalid_file(tmp_path):
    assert read_json_file(tmp_path / "missing.json", {"ok": False}) == {"ok": False}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    assert read_json_file(invalid, []) == []


def test_read_json_file_returns_fallback_for_oversized_file(tmp_path):
    oversized = tmp_path / "oversized.json"
    oversized.write_text("x" * (READ_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    assert read_json_file(oversized, {"fallback": True}) == {"fallback": True}


def test_write_json_atomic_creates_parent_and_writes_json(tmp_path):
    target = tmp_path / "nested" / "data.json"

    write_json_atomic(target, {"name": "autotoken"})

    assert read_json_file(target, {}) == {"name": "autotoken"}
    assert not list(target.parent.glob("*.tmp"))


def test_read_lines_file_returns_missing_as_empty_and_reads_normal_file(tmp_path):
    assert read_lines_file(tmp_path / "missing.txt") == []

    target = tmp_path / "pool.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    assert read_lines_file(target) == ["alpha", "beta"]


def test_read_lines_file_rejects_oversized_file(tmp_path):
    target = tmp_path / "pool.txt"
    target.write_text("123456", encoding="utf-8")

    with pytest.raises(ValueError, match="文件过大"):
        read_lines_file(target, max_bytes=5)


def test_append_unique_non_comment_lines_preserves_comments_and_counts_duplicates(tmp_path):
    target = tmp_path / "pool.txt"
    target.write_text("# comment\nalpha\n", encoding="utf-8")

    result = append_unique_non_comment_lines(target, ["alpha", " beta ", "# skipped", "", "gamma"])

    assert result == {"added": 2, "duplicates": 1}
    assert target.read_text(encoding="utf-8") == "# comment\nalpha\nbeta\ngamma\n"


def test_append_unique_non_comment_lines_does_not_overwrite_oversized_file(tmp_path):
    target = tmp_path / "pool.txt"
    original = "x" * (READ_LINES_FILE_MAX_BYTES + 1)
    target.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="文件过大"):
        append_unique_non_comment_lines(target, ["new-line"])

    assert target.read_text(encoding="utf-8") == original
