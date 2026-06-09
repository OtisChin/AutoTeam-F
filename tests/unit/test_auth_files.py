from autotoken.storage.auth_files import (
    codex_auth_path,
    delete_auth_file,
    is_inside_auth_dir,
    iter_auth_files_for_email,
    trusted_auth_file_path,
    trusted_auth_or_session_path,
)


def test_iter_auth_files_for_email_treats_glob_metacharacters_literally(tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    literal = auth_dir / "codex-user[abc]@example.com-plus-deadbeef.json"
    wildcard_match = auth_dir / "codex-usera@example.com-plus-deadbeef.json"
    literal.write_text("{}", encoding="utf-8")
    wildcard_match.write_text("{}", encoding="utf-8")

    matches = list(iter_auth_files_for_email("user[abc]@example.com", auth_dir=auth_dir))

    assert matches == [literal]


def test_codex_auth_path_sanitizes_fragments_inside_auth_dir(tmp_path):
    auth_dir = tmp_path / "auths"
    path = codex_auth_path(
        email="user@example.com/../../outside",
        plan_type="plus/../../outside",
        account_id="acc/../../outside",
        auth_dir=auth_dir,
    )

    assert path.parent == auth_dir
    assert path.name.startswith("codex-user@example.com_.._.._outside-plus_.._.._outside-")


def test_delete_auth_file_refuses_paths_outside_auth_dir(tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    inside = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    outside = tmp_path / "codex-user@example.com-plus-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")

    assert is_inside_auth_dir(inside, auth_dir=auth_dir) is True
    assert delete_auth_file(outside, auth_dir=auth_dir) is False
    assert outside.exists()
    assert delete_auth_file(inside, auth_dir=auth_dir) is True
    assert not inside.exists()


def test_trusted_auth_file_path_only_accepts_auth_dir_files(tmp_path):
    auth_dir = tmp_path / "auths"
    auth_dir.mkdir()
    inside = auth_dir / "codex-user@example.com-plus-deadbeef.json"
    outside = tmp_path / "codex-user@example.com-plus-deadbeef.json"
    inside.write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")

    assert trusted_auth_file_path(inside, auth_dir=auth_dir) == inside
    assert trusted_auth_file_path(outside, auth_dir=auth_dir) is None


def test_trusted_auth_or_session_path_accepts_auth_session_dir(tmp_path):
    auth_dir = tmp_path / "auths"
    session_dir = tmp_path / "auth_session"
    auth_dir.mkdir()
    session_dir.mkdir()
    session_file = session_dir / "user@example_com.json"
    outside = tmp_path / "user@example_com.json"
    session_file.write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")

    assert trusted_auth_or_session_path(session_file, auth_dir=auth_dir, auth_session_dir=session_dir) == session_file
    assert trusted_auth_or_session_path(outside, auth_dir=auth_dir, auth_session_dir=session_dir) is None
