import json
from pathlib import Path

from autotoken.integrations import cpa_sync
from autotoken.storage import auth_storage
from autotoken.storage.auth_files import AUTH_JSON_FILE_MAX_BYTES


def _codex_auth(email: str, account_id: str = "acc-user") -> dict:
    return {
        "type": "codex",
        "email": email,
        "account_id": account_id,
        "access_token": "access-token",
        "id_token": "id-token",
        "refresh_token": "refresh-token",
        "expired": "2030-01-01T00:00:00Z",
    }


def _patch_auth_dir(monkeypatch, tmp_path: Path) -> Path:
    auth_dir = tmp_path / "data" / "auths"
    auth_dir.mkdir(parents=True)
    monkeypatch.setattr(cpa_sync, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_storage, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(cpa_sync, "upsert_codex_auth_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cpa_sync, "delete_codex_auth_file", lambda *_args, **_kwargs: None)
    return auth_dir


def test_update_local_auth_plan_type_matches_email_glob_chars_literally(tmp_path, monkeypatch):
    auth_dir = _patch_auth_dir(monkeypatch, tmp_path)
    literal = auth_dir / "codex-user[abc]@example.com-unknown-deadbeef.json"
    wildcard_match = auth_dir / "codex-usera@example.com-unknown-deadbeef.json"
    literal.write_text(json.dumps(_codex_auth("user[abc]@example.com", "acc-literal")), encoding="utf-8")
    wildcard_match.write_text(json.dumps(_codex_auth("usera@example.com", "acc-wildcard")), encoding="utf-8")

    result = cpa_sync.update_local_auth_plan_type("user[abc]@example.com", plan_type="plus")

    updated_path = Path(result["auth_file"])
    assert result["status"] == "updated"
    assert updated_path.parent == auth_dir
    assert updated_path.name.startswith("codex-user_abc_@example.com-plus-")
    assert not literal.exists()
    assert wildcard_match.exists()


def test_update_local_auth_plan_type_ignores_preferred_path_outside_auth_dir(tmp_path, monkeypatch):
    auth_dir = _patch_auth_dir(monkeypatch, tmp_path)
    outside = tmp_path / "outside" / "codex-user@example.com-unknown-deadbeef.json"
    outside.parent.mkdir()
    outside.write_text(json.dumps(_codex_auth("user@example.com")), encoding="utf-8")

    result = cpa_sync.update_local_auth_plan_type(
        "user@example.com",
        preferred_path=str(outside),
        plan_type="plus",
    )

    assert result == {"status": "skipped", "reason": "auth_file_not_found", "plan_type": "plus"}
    assert outside.exists()
    assert list(auth_dir.glob("*.json")) == []


def test_update_local_auth_plan_type_skips_oversized_auth_file(tmp_path, monkeypatch):
    auth_dir = _patch_auth_dir(monkeypatch, tmp_path)
    oversized = auth_dir / "codex-user@example.com-unknown-deadbeef.json"
    oversized.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    result = cpa_sync.update_local_auth_plan_type("user@example.com", plan_type="plus")

    assert result == {"status": "skipped", "reason": "auth_file_not_found", "plan_type": "plus"}
    assert oversized.exists()


def test_ensure_cpa_compatible_auth_file_skips_oversized_preferred_file(tmp_path, monkeypatch):
    _patch_auth_dir(monkeypatch, tmp_path)
    oversized = tmp_path / "codex-user@example.com-session.json"
    oversized.write_text("x" * (AUTH_JSON_FILE_MAX_BYTES + 1), encoding="utf-8")

    assert cpa_sync.ensure_cpa_compatible_auth_file(oversized, fallback_email="user@example.com") == ""


def test_save_normalized_auth_file_keeps_filename_fragments_inside_auth_dir(tmp_path, monkeypatch):
    auth_dir = _patch_auth_dir(monkeypatch, tmp_path)
    bundle = {
        "email": "user@example.com/../../outside",
        "account_id": "acc/../../outside",
        "access_token": "access-token",
        "id_token": "id-token",
        "refresh_token": "refresh-token",
        "plan_type": "plus/../../outside",
        "expired": 1893456000,
    }

    path = Path(cpa_sync._save_normalized_auth_file(bundle))

    assert path.resolve().relative_to(auth_dir.resolve())
    assert path.name.startswith("codex-user@example.com_.._.._outside-plus_.._.._outside-")
    assert not (tmp_path / "outside.json").exists()
