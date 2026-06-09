from autotoken.core.archive import safe_archive_member_name, safe_archive_path_segment


def test_safe_archive_member_name_strips_paths_and_sanitizes_stem():
    assert safe_archive_member_name("../nested\\evil:name.json", fallback="auth.json") == "evil_name.json"


def test_safe_archive_member_name_enforces_allowed_suffix():
    assert (
        safe_archive_member_name(
            "payload.txt",
            fallback="auth.json",
            default_suffix=".json",
            allowed_suffixes={".json"},
        )
        == "payload.json"
    )


def test_safe_archive_member_name_can_sanitize_generated_names_without_dropping_prefix():
    assert (
        safe_archive_member_name(
            "codex-shared-../../evil@example.com.json",
            fallback="auth.json",
            default_suffix=".json",
            allowed_suffixes={".json"},
            strip_paths=False,
        )
        == "codex-shared-.._.._evil@example.com.json"
    )


def test_safe_archive_path_segment_sanitizes_batch_ids():
    assert safe_archive_path_segment("001-20260609-../evil/batch") == "001-20260609-.._evil_batch"
