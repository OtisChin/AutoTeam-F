import ast
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import warnings
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlsplit

import tomllib

RUNTIME_AUTOTEAM_REFERENCE_ALLOWLIST = {
    Path("src/autotoken/core/env.py"),
    Path("src/autotoken/core/oauth_helper.py"),
    Path("src/autotoken/oauth_helper_extension/content.js"),
    Path("src/autotoken/storage/sqlite_store.py"),
}

DOCS_AND_CONFIG_AUTOTEAM_REFERENCE_ALLOWLIST = {
    Path("pyproject.toml"),
}

def _is_planning_record(relative: Path) -> bool:
    return relative.parts[:2] == ("docs", "plans") or relative.parts[:3] in {
        ("docs", "superpowers", "plans"),
        ("docs", "superpowers", "specs"),
    }

def _autoteam_alias_mapping_from_text(text: str) -> dict[str, str]:
    module = ast.parse(text)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "_REORGANIZED_SUBMODULE_ALIASES" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("_REORGANIZED_SUBMODULE_ALIASES assignment not found")

def _nested_implementation_module_suffixes(project_root: Path) -> list[str]:
    source_root = project_root / "src" / "autotoken"
    suffixes = []
    for path in sorted(source_root.rglob("*.py")):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        relative = path.relative_to(source_root).with_suffix("")
        if len(relative.parts) == 1:
            continue
        suffixes.append(".".join(relative.parts))
    return suffixes

def _python_package_dirs_missing_init(source_root: Path) -> list[str]:
    package_dirs = sorted({path.parent for path in source_root.rglob("*.py")})
    return [
        directory.relative_to(source_root).as_posix()
        for directory in package_dirs
        if directory != source_root and not (directory / "__init__.py").is_file()
    ]

def _wheel_python_package_dirs_missing_init(wheel_names: list[str]) -> list[str]:
    package_dirs = sorted(
        {
            str(Path(name).parent).replace("\\", "/")
            for name in wheel_names
            if name.startswith("autotoken/") and name.endswith(".py")
        }
    )
    return [
        directory
        for directory in package_dirs
        if directory != "autotoken" and f"{directory}/__init__.py" not in wheel_names
    ]

def _protocol_register_bundle_files(project_root: Path) -> list[str]:
    bundle_root = project_root / "src" / "autotoken" / "_protocol_register"
    return sorted(path.relative_to(bundle_root).as_posix() for path in bundle_root.iterdir() if path.is_file())

def _oauth_helper_extension_files(project_root: Path) -> list[str]:
    extension_root = project_root / "src" / "autotoken" / "oauth_helper_extension"
    return sorted(path.relative_to(extension_root).as_posix() for path in extension_root.iterdir() if path.is_file())

def _autotoken_package_data_files(project_root: Path) -> list[str]:
    package_root = project_root / "src" / "autotoken"
    return sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and path.suffix != ".py"
        and "__pycache__" not in path.parts
        and path.relative_to(package_root).parts[:2] != ("web", "dist")
    )

def _text_artifact_members_containing_old_name(members: dict[str, str]) -> list[str]:
    old_name_terms = ("autoteam", "AutoTeam", "AUTOTEAM")
    return sorted(
        name
        for name, text in members.items()
        if "autoteam" in name.lower() or any(term in text for term in old_name_terms)
    )

def _removed_subsystem_marker_patterns() -> tuple[re.Pattern[str], ...]:
    snake_name = "gopay" + "_pro"
    kebab_name = "gopay" + "-pro"
    legacy_name = "cn" + "gopay"
    display_name = "GoPay" + " " + "Pro"
    camel_type_name = "GoPay" + "Pro"
    camel_value_name = "gopay" + "Pro"
    return (
        re.compile(
            rf"{re.escape(snake_name)}(?:_|\b)|"
            rf"{re.escape(kebab_name)}(?:-|\b)|"
            rf"{re.escape(legacy_name)}|"
            rf"{re.escape(display_name)}\b",
            flags=re.IGNORECASE,
        ),
        re.compile(rf"{re.escape(camel_type_name)}[A-Z]|\b{re.escape(camel_value_name)}\b"),
    )

def _contains_removed_subsystem_marker(value: str | bytes) -> bool:
    patterns = _removed_subsystem_marker_patterns()
    if isinstance(value, bytes):
        return any(
            re.search(pattern.pattern.encode("ascii"), value, flags=pattern.flags & ~re.UNICODE) for pattern in patterns
        )
    return any(pattern.search(value) for pattern in patterns)

def _allowed_removal_record_paths(canonical_root: PurePosixPath) -> set[PurePosixPath]:
    record_stem = "2026-07-13-remove-" + "gopay" + "-pro"
    return {
        canonical_root / "docs/superpowers/specs" / f"{record_stem}-design.md",
        canonical_root / "docs/superpowers/plans" / f"{record_stem}.md",
    }

def _wheel_removed_subsystem_hits(wheel_path: Path) -> list[str]:
    hits = set()
    seen_names = set()

    with zipfile.ZipFile(wheel_path) as wheel:
        for info in wheel.infolist():
            name = info.filename
            if name in seen_names:
                hits.add(f"duplicate member: {name}")
            seen_names.add(name)
            if _contains_removed_subsystem_marker(name):
                hits.add(f"member: {name}")
            payload = wheel.read(info)
            if _contains_removed_subsystem_marker(payload):
                hits.add(f"content: {name}")
            if info.is_dir() and info.file_size != 0:
                hits.add(f"directory member has payload: {name}")

    return sorted(hits)

def _sdist_removed_subsystem_hits(
    sdist_path: Path,
    canonical_root: PurePosixPath,
    allowed_records: set[PurePosixPath],
) -> list[str]:
    hits = set()
    allowed_record_members = {record: [] for record in allowed_records}

    with tarfile.open(sdist_path) as sdist:
        for member in sdist.getmembers():
            member_path = PurePosixPath(member.name)
            if member_path in allowed_record_members:
                allowed_record_members[member_path].append(member)

            if "\\" in member.name or member_path.is_absolute() or ".." in member_path.parts:
                hits.add(f"unsafe member path: {member.name}")
                has_canonical_root = False
            else:
                has_canonical_root = member_path == canonical_root or (
                    member_path.parts[: len(canonical_root.parts)] == canonical_root.parts
                )
                if not has_canonical_root:
                    hits.add(f"noncanonical member root: {member.name}")

            if has_canonical_root and member_path in allowed_records and member.isfile():
                continue
            if _contains_removed_subsystem_marker(member.name):
                hits.add(f"member: {member.name}")
            if member.issym() or member.islnk():
                link_path = PurePosixPath(member.linkname)
                if _contains_removed_subsystem_marker(member.linkname):
                    hits.add(f"link target marker: {member.name} -> {member.linkname}")
                if "\\" in member.linkname or link_path.is_absolute() or ".." in link_path.parts:
                    hits.add(f"unsafe link target: {member.name} -> {member.linkname}")
            if not member.isfile() and not member.isdir():
                hits.add(f"unsupported member type: {member.name}")
            if not member.isfile():
                continue
            member_file = sdist.extractfile(member)
            if member_file is None:
                continue
            if _contains_removed_subsystem_marker(member_file.read()):
                hits.add(f"content: {member.name}")

    for record, members in allowed_record_members.items():
        if len(members) != 1:
            hits.add(f"allowed removal record count: {record}: {len(members)}")
        if any(not member.isfile() for member in members):
            hits.add(f"allowed removal record is not a regular file: {record}")

    return sorted(hits)

def test_removed_subsystem_marker_detection_matches_only_retired_identifiers():
    legacy_name = "cn" + "gopay"
    positive_values = [
        "gopay" + "_pro",
        "gopay" + "-pro",
        "CN" + "gopay" + "Backup",
        legacy_name + "2",
        "GoPay" + " " + "Pro",
        "GoPay" + "ProTask",
        "gopay" + "Pro",
    ]
    negative_values = [
        "gopay_protocol",
        "gopayProxy",
    ]

    assert all(_contains_removed_subsystem_marker(value) for value in positive_values)
    assert not any(_contains_removed_subsystem_marker(value) for value in negative_values)

def _write_test_sdist(sdist_path: Path, members: list[tuple[str, bytes | None]]) -> None:
    with tarfile.open(sdist_path, "w:gz") as sdist:
        for name, payload in members:
            member = tarfile.TarInfo(name)
            if payload is None:
                member.type = tarfile.DIRTYPE
                sdist.addfile(member)
                continue
            member.size = len(payload)
            sdist.addfile(member, io.BytesIO(payload))

def test_wheel_archive_scan_checks_raw_bytes(tmp_path):
    wheel_path = tmp_path / "fixture.whl"
    retired_payload = b"\xff" + ("cn" + "gopay" + "Backup").encode("ascii")

    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("payload.bin", retired_payload)

    assert _wheel_removed_subsystem_hits(wheel_path) == ["content: payload.bin"]

def test_wheel_archive_scan_rejects_duplicate_names_and_reads_each_entry(tmp_path):
    wheel_path = tmp_path / "fixture.whl"
    retired_payload = ("cn" + "gopay" + "Backup").encode("ascii")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(wheel_path, "w") as wheel:
            wheel.writestr("payload.txt", retired_payload)
            wheel.writestr("payload.txt", b"clean")

    assert _wheel_removed_subsystem_hits(wheel_path) == [
        "content: payload.txt",
        "duplicate member: payload.txt",
    ]

def test_wheel_archive_scan_rejects_directory_entries_with_payload(tmp_path):
    wheel_path = tmp_path / "fixture.whl"
    retired_payload = ("CN" + "gopay" + "Backup").encode("ascii")

    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("payload/", retired_payload)

    assert _wheel_removed_subsystem_hits(wheel_path) == [
        "content: payload/",
        "directory member has payload: payload/",
    ]

def test_sdist_archive_scan_checks_raw_bytes(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    retired_payload = b"\xff" + ("cn" + "gopay" + "Backup").encode("ascii")
    members = [(record.as_posix(), b"removal record") for record in allowed_records]
    members.append(((canonical_root / "payload.bin").as_posix(), retired_payload))
    _write_test_sdist(sdist_path, members)

    assert _sdist_removed_subsystem_hits(sdist_path, canonical_root, allowed_records) == [
        f"content: {canonical_root}/payload.bin"
    ]

def test_sdist_archive_scan_rejects_noncanonical_member_paths(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    members = [(record.as_posix(), b"removal record") for record in allowed_records]
    members.extend(
        [
            ("/absolute.txt", b"clean"),
            (f"{canonical_root}/../escape.txt", b"clean"),
            ("other-root/clean.txt", b"clean"),
        ]
    )
    _write_test_sdist(sdist_path, members)

    assert _sdist_removed_subsystem_hits(sdist_path, canonical_root, allowed_records) == [
        "noncanonical member root: other-root/clean.txt",
        "unsafe member path: /absolute.txt",
        f"unsafe member path: {canonical_root}/../escape.txt",
    ]

def test_sdist_archive_scan_rejects_backslash_member_names(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    unsafe_name = f"{canonical_root}/dir\\..\\..\\escape"
    members = [(record.as_posix(), b"removal record") for record in allowed_records]
    members.append((unsafe_name, b"clean"))
    _write_test_sdist(sdist_path, members)

    assert _sdist_removed_subsystem_hits(sdist_path, canonical_root, allowed_records) == [
        f"unsafe member path: {unsafe_name}"
    ]

def test_sdist_archive_scan_rejects_links_and_scans_targets(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    marker_link_name = "CN" + "gopay" + "Backup"
    symlink_name = (canonical_root / "marker-link").as_posix()
    hardlink_name = (canonical_root / "escape-link").as_posix()

    with tarfile.open(sdist_path, "w:gz") as sdist:
        for record in allowed_records:
            payload = b"removal record"
            member = tarfile.TarInfo(record.as_posix())
            member.size = len(payload)
            sdist.addfile(member, io.BytesIO(payload))

        symlink = tarfile.TarInfo(symlink_name)
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = marker_link_name
        sdist.addfile(symlink)

        hardlink = tarfile.TarInfo(hardlink_name)
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "../../escape"
        sdist.addfile(hardlink)

    hits = _sdist_removed_subsystem_hits(sdist_path, canonical_root, allowed_records)

    assert f"link target marker: {symlink_name} -> {marker_link_name}" in hits
    assert f"unsafe link target: {hardlink_name} -> ../../escape" in hits
    assert f"unsupported member type: {symlink_name}" in hits
    assert f"unsupported member type: {hardlink_name}" in hits

def test_sdist_archive_scan_does_not_allow_records_under_another_root(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    allowed_record = next(iter(allowed_records))
    alternate_record = PurePosixPath("other-root", *allowed_record.parts[1:])
    members = [(record.as_posix(), b"removal record") for record in allowed_records]
    members.append((alternate_record.as_posix(), b"removal record"))
    _write_test_sdist(sdist_path, members)

    assert f"noncanonical member root: {alternate_record}" in _sdist_removed_subsystem_hits(
        sdist_path, canonical_root, allowed_records
    )

def test_sdist_archive_scan_requires_each_allowed_record_once_as_a_regular_file(tmp_path):
    sdist_path = tmp_path / "fixture.tar.gz"
    canonical_root = PurePosixPath("autotoken-0.1.0")
    allowed_records = _allowed_removal_record_paths(canonical_root)
    missing_record, repeated_record = sorted(allowed_records, key=str)
    _write_test_sdist(
        sdist_path,
        [
            (repeated_record.as_posix(), b"removal record"),
            (repeated_record.as_posix(), None),
        ],
    )

    hits = _sdist_removed_subsystem_hits(sdist_path, canonical_root, allowed_records)

    assert f"allowed removal record count: {missing_record}: 0" in hits
    assert f"allowed removal record count: {repeated_record}: 2" in hits
    assert f"allowed removal record is not a regular file: {repeated_record}" in hits

def _legacy_root_alias_metadata_check_script(checks: dict[str, str]) -> str:
    return f"""
import importlib

checks = {checks!r}

for legacy_suffix, canonical_name in checks.items():
    legacy_name = "autoteam." + legacy_suffix
    legacy_module = importlib.import_module(legacy_name)
    canonical_module = importlib.import_module(canonical_name)
    assert legacy_module is canonical_module, (legacy_name, legacy_module, canonical_module)
    assert legacy_module.__name__ == canonical_name, (legacy_name, legacy_module.__name__)
    assert legacy_module.__package__ == canonical_module.__package__, (legacy_name, legacy_module.__package__)
    assert legacy_module.__spec__.name == canonical_name, (legacy_name, legacy_module.__spec__.name)
"""

def test_autoteam_reference_allowlists_are_not_stale():
    project_root = Path(__file__).resolve().parents[2]
    allowlists = {
        "runtime": RUNTIME_AUTOTEAM_REFERENCE_ALLOWLIST,
        "docs/config": DOCS_AND_CONFIG_AUTOTEAM_REFERENCE_ALLOWLIST,
    }
    offenders = []

    for name, allowlist in allowlists.items():
        for relative_path in sorted(allowlist):
            path = project_root / relative_path
            if not path.is_file():
                offenders.append(f"{name}: {relative_path.as_posix()} is missing")
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not any(term in text for term in ("autoteam", "AutoTeam", "AUTOTEAM")):
                offenders.append(f"{name}: {relative_path.as_posix()} no longer contains old-name references")

    assert offenders == []

def test_legacy_autoteam_import_aliases_autotoken():
    import autoteam
    import autotoken

    assert autoteam is autotoken

def test_legacy_autoteam_submodule_imports_resolve_canonical_modules():
    legacy_cloudmail = importlib.import_module("autoteam.cloudmail")
    legacy_manager = importlib.import_module("autoteam.manager")
    cloudmail = importlib.import_module("autotoken.cloudmail")
    manager = importlib.import_module("autotoken.manager")

    assert legacy_cloudmail is cloudmail
    assert legacy_manager is manager
    assert legacy_cloudmail.CloudMailClient is cloudmail.CloudMailClient
    assert legacy_manager.main is manager.main

def test_legacy_autoteam_submodule_imports_do_not_load_root_wrappers(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    checks = _autoteam_alias_mapping_from_text(
        (project_root / "src" / "autoteam" / "__init__.py").read_text(encoding="utf-8")
    )
    script = f"""
import importlib
import sys

checks = {checks!r}

for legacy_suffix, canonical_name in checks.items():
    legacy_name = "autoteam." + legacy_suffix
    legacy_module = importlib.import_module(legacy_name)
    canonical_module = importlib.import_module(canonical_name)
    root_wrapper_name = "autotoken." + legacy_suffix
    assert legacy_module is canonical_module, (legacy_name, legacy_module, canonical_module)
    assert root_wrapper_name not in sys.modules, (legacy_name, root_wrapper_name)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout

def test_legacy_autoteam_root_aliases_preserve_canonical_module_metadata(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    checks = _autoteam_alias_mapping_from_text(
        (project_root / "src" / "autoteam" / "__init__.py").read_text(encoding="utf-8")
    )
    result = subprocess.run(
        [sys.executable, "-c", _legacy_root_alias_metadata_check_script(checks)],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout

def test_legacy_autoteam_shim_maps_all_root_wrappers_directly_to_canonical_targets():
    project_root = Path(__file__).resolve().parents[2]
    package_root = project_root / "src" / "autotoken"
    expected_aliases = {}

    for path in sorted(package_root.glob("*.py")):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'^"""Compatibility wrapper for ``([^`]+)``\."""', text)
        assert match, f"{path.relative_to(project_root).as_posix()} is not a compatibility wrapper"
        expected_aliases[path.stem] = match.group(1)

    shim_text = (project_root / "src" / "autoteam" / "__init__.py").read_text(encoding="utf-8")

    assert _autoteam_alias_mapping_from_text(shim_text) == expected_aliases

def test_legacy_autoteam_nested_submodule_specs_follow_canonical_layout():
    project_root = Path(__file__).resolve().parents[2]
    offenders = []

    for module_suffix in _nested_implementation_module_suffixes(project_root):
        legacy_spec = importlib.util.find_spec(f"autoteam.{module_suffix}")
        canonical_spec = importlib.util.find_spec(f"autotoken.{module_suffix}")
        legacy_origin = getattr(legacy_spec, "origin", None)
        canonical_origin = getattr(canonical_spec, "origin", None)
        if legacy_origin != canonical_origin:
            offenders.append(f"{module_suffix}: legacy={legacy_origin!r} canonical={canonical_origin!r}")

    assert offenders == []

def test_legacy_autoteam_package_aliases_preserve_canonical_module_metadata(tmp_path):
    script = """
import importlib

package_suffixes = [
    "_protocol_register",
    "api_routes",
    "auth",
    "core",
    "interfaces",
    "payments",
    "storage",
]

for suffix in package_suffixes:
    legacy_module = importlib.import_module("autoteam." + suffix)
    canonical_name = "autotoken." + suffix
    canonical_module = importlib.import_module(canonical_name)
    assert legacy_module is canonical_module, (suffix, legacy_module, canonical_module)
    assert legacy_module.__name__ == canonical_name, (suffix, legacy_module.__name__)
    assert legacy_module.__package__ == canonical_name, (suffix, legacy_module.__package__)
    assert legacy_module.__spec__.name == canonical_name, (suffix, legacy_module.__spec__.name)
    assert list(legacy_module.__path__) == list(canonical_module.__path__), suffix
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout

def test_autotoken_python_subpackages_have_explicit_initializers():
    project_root = Path(__file__).resolve().parents[2]

    assert _python_package_dirs_missing_init(project_root / "src" / "autotoken") == []

def test_autotoken_root_contains_only_entrypoints_and_compatibility_wrappers():
    project_root = Path(__file__).resolve().parents[2]
    package_root = project_root / "src" / "autotoken"
    allowed_entrypoints = {"__init__.py", "__main__.py"}
    offenders = []

    for path in sorted(package_root.glob("*.py")):
        if path.name in allowed_entrypoints:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Compatibility wrapper for" not in text or "_sys.modules[__name__] = _impl" not in text:
            offenders.append(path.name)

    assert offenders == []

def test_active_python_scripts_use_canonical_imports_for_reorganized_helpers():
    project_root = Path(__file__).resolve().parents[2]
    package_root = project_root / "src" / "autotoken"
    root_wrapper_names = {
        path.stem
        for path in package_root.glob("*.py")
        if path.name not in {"__init__.py", "__main__.py"}
        and "Compatibility wrapper for" in path.read_text(encoding="utf-8", errors="ignore")
    }
    offenders = []

    for path in sorted((project_root / "scripts").glob("*.py")):
        relative = path.relative_to(project_root)
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if len(parts) >= 2 and parts[0] == "autotoken" and parts[1] in root_wrapper_names:
                        offenders.append(f"{relative.as_posix()}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name == "autotoken":
                    for alias in node.names:
                        if alias.name in root_wrapper_names:
                            offenders.append(f"{relative.as_posix()}: from autotoken import {alias.name}")
                elif module_name.startswith("autotoken."):
                    parts = module_name.split(".")
                    if len(parts) >= 2 and parts[1] in root_wrapper_names:
                        offenders.append(f"{relative.as_posix()}: from {module_name} import ...")

    assert offenders == []

def test_built_wheel_root_contains_only_entrypoints_and_compatibility_wrappers():
    project_root = Path(__file__).resolve().parents[2]
    wheel_path = project_root / "dist" / "autotoken-0.1.0-py3-none-any.whl"
    allowed_entrypoints = {"autotoken/__init__.py", "autotoken/__main__.py"}
    offenders = []

    assert wheel_path.is_file()

    with zipfile.ZipFile(wheel_path) as wheel:
        root_modules = sorted(
            name
            for name in wheel.namelist()
            if name.startswith("autotoken/") and name.count("/") == 1 and name.endswith(".py")
        )
        for name in root_modules:
            if name in allowed_entrypoints:
                continue
            text = wheel.read(name).decode("utf-8", errors="ignore")
            if "Compatibility wrapper for" not in text or "_sys.modules[__name__] = _impl" not in text:
                offenders.append(name)

    assert offenders == []

def test_paths_module_keeps_project_root_at_repository_root():
    import autotoken.paths as paths

    project_root = Path(__file__).resolve().parents[2]

    assert paths.PROJECT_ROOT == project_root

def test_protocol_register_loads_bundled_protocol_modules_after_reorganization():
    import autotoken.protocol_register as protocol_register

    auth_flow, config = protocol_register._load_protocol_classes()

    assert auth_flow.__name__ == "AuthFlow"
    assert config.__name__ == "Config"

def test_codex_auth_oauth_helper_extension_path_survives_reorganization():
    import autotoken.codex_auth as codex_auth

    project_root = Path(__file__).resolve().parents[2]

    assert codex_auth.OAUTH_HELPER_EXTENSION_DIR == project_root / "src" / "autotoken" / "oauth_helper_extension"
    assert (codex_auth.OAUTH_HELPER_EXTENSION_DIR / "manifest.json").is_file()

def test_api_static_dist_path_survives_reorganization():
    import autotoken.api as api

    project_root = Path(__file__).resolve().parents[2]

    assert api.DIST_DIR == project_root / "src" / "autotoken" / "web" / "dist"
    assert (api.DIST_DIR / "index.html").is_file()

def test_legacy_autoteam_package_contains_only_compatibility_entrypoints():
    project_root = Path(__file__).resolve().parents[2]
    legacy_files = {
        path.relative_to(project_root).as_posix()
        for path in (project_root / "src" / "autoteam").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert legacy_files == {"src/autoteam/__init__.py", "src/autoteam/__main__.py"}

def test_legacy_autoteam_module_entrypoint_uses_canonical_manager():
    project_root = Path(__file__).resolve().parents[2]
    entrypoint = (project_root / "src" / "autoteam" / "__main__.py").read_text(encoding="utf-8")

    assert "from autotoken.interfaces.manager import main" in entrypoint
    assert "autotoken.manager" not in entrypoint

def test_legacy_autoteam_env_var_alias(monkeypatch):
    monkeypatch.delenv("AUTOTOKEN_LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("AUTOTEAM_LOCAL_BASE_URL", "http://legacy.example")

    import autotoken

    autotoken.install_legacy_env_aliases()

    assert os.environ["AUTOTOKEN_LOCAL_BASE_URL"] == "http://legacy.example"

def test_legacy_autoteam_env_var_alias_beats_env_file_defaults():
    from autotoken.core.env import set_env_default_with_legacy_alias

    environ = {"AUTOTEAM_DB_FILE": "legacy-runtime.sqlite3"}

    set_env_default_with_legacy_alias("AUTOTOKEN_DB_FILE", "autotoken-env-file.sqlite3", environ)

    assert environ["AUTOTOKEN_DB_FILE"] == "legacy-runtime.sqlite3"

def test_canonical_autotoken_env_var_keeps_priority_over_legacy_alias():
    from autotoken.core.env import set_env_default_with_legacy_alias

    environ = {
        "AUTOTOKEN_DB_FILE": "canonical-runtime.sqlite3",
        "AUTOTEAM_DB_FILE": "legacy-runtime.sqlite3",
    }

    set_env_default_with_legacy_alias("AUTOTOKEN_DB_FILE", "autotoken-env-file.sqlite3", environ)

    assert environ["AUTOTOKEN_DB_FILE"] == "canonical-runtime.sqlite3"

def test_legacy_autoteam_env_file_default_uses_existing_legacy_runtime_value():
    from autotoken.core.env import set_env_default_with_legacy_alias

    environ = {"AUTOTEAM_DB_FILE": "legacy-runtime.sqlite3"}

    set_env_default_with_legacy_alias("AUTOTEAM_DB_FILE", "legacy-env-file.sqlite3", environ)

    assert environ["AUTOTEAM_DB_FILE"] == "legacy-runtime.sqlite3"
    assert environ["AUTOTOKEN_DB_FILE"] == "legacy-runtime.sqlite3"

def test_sqlite_store_uses_legacy_db_when_new_db_missing(tmp_path, monkeypatch):
    import autotoken.sqlite_store as sqlite_store

    legacy_db = tmp_path / "autoteam.sqlite3"
    legacy_db.write_text("", encoding="utf-8")
    new_db = tmp_path / "autotoken.sqlite3"

    monkeypatch.setattr(sqlite_store, "LEGACY_DB_FILE", legacy_db)
    monkeypatch.setattr(sqlite_store, "DB_FILE", new_db)
    monkeypatch.delenv("AUTOTOKEN_DB_FILE", raising=False)
    monkeypatch.delenv("AUTOTEAM_DB_FILE", raising=False)

    assert sqlite_store.default_db_path() == legacy_db

def test_pyproject_uses_autotoken_as_canonical_cli_and_keeps_autoteam_alias():
    project_root = Path(__file__).resolve().parents[2]
    pyproject_text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)

    assert pyproject["project"]["name"] == "autotoken"
    assert set(pyproject["project"]["scripts"]) == {"autotoken", "autoteam"}
    assert pyproject["project"]["scripts"]["autotoken"] == "autotoken.interfaces.manager:main"
    assert pyproject["project"]["scripts"]["autoteam"] == "autotoken.interfaces.manager:main"
    required_sdist_excludes = {
        "/.codex",
        "/.codex_tmp",
        "/.pytest_cache",
        "/.pytest_tmp*",
        "/.ruff_cache",
        "/.uv-cache",
        "/.verify",
        "/.venv",
        "/build",
        "/dist",
        "/auth_state",
        "/auths",
        "/auths.bak-*",
        "/data",
        "/logs",
        "/outputs",
        "/screenshots",
        "/tmp",
        "/web/node_modules",
        "/accounts.json",
        "/bearer_token",
        "/bind_audit.json",
        "/pool.exe",
        "/pool-linux-x64",
        "/pool-mac-arm64",
        "/pool-mac-intel",
        "/register_failures.json",
        "/runtime_config.json",
        "/session",
        "/state.json",
    }
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/autotoken", "src/autoteam"]
    assert required_sdist_excludes <= set(pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])
    assert "AutoTeam" not in pyproject_text
    assert "AUTOTEAM" not in pyproject_text
    assert pyproject_text.count("autoteam") == 2

def test_uv_lock_uses_autotoken_as_editable_project_name():
    project_root = Path(__file__).resolve().parents[2]
    lock_text = (project_root / "uv.lock").read_text(encoding="utf-8")
    uv_lock = tomllib.loads(lock_text)
    editable_packages = [package for package in uv_lock["package"] if package.get("source", {}).get("editable") == "."]

    assert [package["name"] for package in editable_packages] == ["autotoken"]
    assert "autoteam" not in lock_text.lower()

def test_python_module_entrypoints_resolve_canonical_and_legacy_packages():
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src") + os.pathsep + env.get("PYTHONPATH", "")

    for module_name in ("autotoken", "autoteam"):
        result = subprocess.run(
            [sys.executable, "-m", module_name, "--help"],
            cwd=project_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, result.stdout
        assert result.stdout.startswith("usage: autotoken ")
        assert "manager.py" not in result.stdout
        assert "api" in result.stdout

def test_manual_account_helper_url_prefers_autotoken_params_and_keeps_legacy_aliases():
    from autotoken.manual_account import ManualAccountFlow

    flow = object.__new__(ManualAccountFlow)
    flow.direct_auth_url = "https://auth.example/authorize"
    flow._helper_server = type("HelperServer", (), {"token": "secret-token", "port": 4711})()

    fragment = parse_qs(urlsplit(flow._helper_auth_url()).fragment)

    assert fragment["autotoken_token"] == ["secret-token"]
    assert fragment["autotoken_port"] == ["4711"]
    assert fragment["autotoken_auth"] == ["https://auth.example/authorize"]
    assert fragment["autoteam_token"] == ["secret-token"]
    assert fragment["autoteam_port"] == ["4711"]
    assert fragment["autoteam_auth"] == ["https://auth.example/authorize"]

def test_runtime_autoteam_references_are_limited_to_compatibility_shims():
    project_root = Path(__file__).resolve().parents[2]
    runtime_root = project_root / "src" / "autotoken"
    offenders = []

    for path in runtime_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if relative in RUNTIME_AUTOTEAM_REFERENCE_ALLOWLIST:
            continue
        if any(part == "__pycache__" for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "autoteam" in text.lower():
            offenders.append(str(relative).replace("\\", "/"))

    assert offenders == []

def test_mixed_case_autoteam_brand_references_are_limited_to_plans_and_tests():
    project_root = Path(__file__).resolve().parents[2]
    scanned_roots = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "CONTRIBUTING.md",
        project_root / ".env.example",
        project_root / "docker-compose.yml",
        project_root / "docker-entrypoint.sh",
        project_root / "deploy-local.ps1",
        project_root / "setup.sh",
        project_root / "pyproject.toml",
        project_root / "src",
        project_root / "docs",
        project_root / "scripts",
        project_root / "web",
    ]
    offenders = []

    for root in scanned_roots:
        paths = root.rglob("*") if root.is_dir() else [root]
        for path in paths:
            if not path.is_file():
                continue
            relative = path.relative_to(project_root)
            if _is_planning_record(relative):
                continue
            if "dist" in relative.parts or "node_modules" in relative.parts or "__pycache__" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "AutoTeam" in text:
                offenders.append(str(relative).replace("\\", "/"))

    assert offenders == []

def test_docs_and_config_autoteam_references_are_limited_to_compatibility_notes():
    project_root = Path(__file__).resolve().parents[2]
    scanned_paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "CONTRIBUTING.md",
        project_root / ".env.example",
        project_root / "docker-compose.yml",
        project_root / "docker-entrypoint.sh",
        project_root / "deploy-local.ps1",
        project_root / "setup.sh",
        project_root / "pyproject.toml",
        *sorted((project_root / "docs").rglob("*.md")),
        *sorted((project_root / "scripts").rglob("*")),
        *sorted((project_root / "web").rglob("*")),
    ]
    offenders = []

    for path in scanned_paths:
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if relative in DOCS_AND_CONFIG_AUTOTEAM_REFERENCE_ALLOWLIST:
            continue
        if _is_planning_record(relative):
            continue
        if "dist" in relative.parts or "node_modules" in relative.parts or "__pycache__" in relative.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text for term in ("autoteam", "AutoTeam", "AUTOTEAM")):
            offenders.append(str(relative).replace("\\", "/"))

    assert offenders == []

def _github_markdown_slug(heading: str) -> str:
    normalized = heading.strip().lower().replace("`", "")
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")

def test_active_markdown_links_resolve_to_existing_local_docs():
    project_root = Path(__file__).resolve().parents[2]
    scanned_paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "CONTRIBUTING.md",
        *sorted((project_root / "docs").glob("*.md")),
    ]
    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    offenders = []

    for source_path in scanned_paths:
        if not source_path.is_file():
            continue
        source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        for match in link_pattern.finditer(source_text):
            raw_target = match.group(1).strip()
            split_target = urlsplit(raw_target)
            if split_target.scheme or split_target.netloc:
                continue
            if not split_target.path.lower().endswith(".md"):
                continue

            target_path = (source_path.parent / unquote(split_target.path)).resolve()
            try:
                relative_target = target_path.relative_to(project_root)
            except ValueError:
                offenders.append(f"{source_path.relative_to(project_root)} -> {raw_target} escapes project")
                continue

            if not target_path.is_file():
                offenders.append(f"{source_path.relative_to(project_root)} -> {relative_target} missing")
                continue

            if split_target.fragment:
                headings = {
                    _github_markdown_slug(heading_match.group(1))
                    for heading_match in re.finditer(
                        r"^#{1,6}\s+(.+)$",
                        target_path.read_text(encoding="utf-8", errors="ignore"),
                        flags=re.MULTILINE,
                    )
                }
                if unquote(split_target.fragment).lower() not in headings:
                    offenders.append(
                        f"{source_path.relative_to(project_root)} -> "
                        f"{relative_target}#{split_target.fragment} missing anchor"
                    )

    assert offenders == []

def test_active_docs_reference_existing_local_source_and_test_files():
    project_root = Path(__file__).resolve().parents[2]
    scanned_paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "CONTRIBUTING.md",
        *sorted((project_root / "docs").rglob("*.md")),
    ]
    local_file_ref_pattern = re.compile(
        r"`?((?:src|tests|scripts|web|docs)/"
        r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+"
        r"\.(?:py|md|vue|js|ts|json|ps1|sh|toml|yml|yaml))`?"
    )
    offenders = []

    for source_path in scanned_paths:
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(project_root)
        if _is_planning_record(relative):
            continue
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        for match in local_file_ref_pattern.finditer(text):
            referenced = match.group(1).replace("\\", "/")
            target = project_root / referenced
            if not target.exists():
                offenders.append(f"{relative.as_posix()}: {referenced}")

    assert offenders == []

def test_tracked_files_do_not_embed_prerename_workspace_paths():
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "grep", "-n", "AutoTeam-F", "--", "."],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1, result.stdout
    assert result.stdout == ""

def test_active_docs_and_scripts_do_not_embed_local_absolute_paths():
    project_root = Path(__file__).resolve().parents[2]
    scanned_paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "CONTRIBUTING.md",
        *sorted((project_root / "docs").rglob("*.md")),
        *sorted((project_root / "scripts").rglob("*")),
    ]
    local_absolute_path_pattern = re.compile(r"(?<![A-Za-z])/?[A-Za-z]:[\\/][^\s`'\"),]+")
    offenders = []

    for path in scanned_paths:
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if _is_planning_record(relative):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = sorted(set(local_absolute_path_pattern.findall(text)))
        if matches:
            offenders.append(f"{relative.as_posix()}: {', '.join(matches)}")

    assert offenders == []

def test_git_tracked_text_files_do_not_contain_high_confidence_secret_values():
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout

    secret_patterns = [
        re.compile(r"(?<![A-Za-z0-9_])sk-(proj-)?[A-Za-z0-9_-]{32,}"),
        re.compile(r"(?<![A-Za-z0-9_])xox[baprs]-[A-Za-z0-9-]{32,}"),
        re.compile(r"(?<![A-Za-z0-9_])AIza[0-9A-Za-z_-]{35}"),
        re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9_]{30,}"),
        re.compile(r"M\.C[0-9]{3}_[A-Z0-9]+\.[^\s\"']{40,}"),
        re.compile(r"eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}"),
        re.compile(
            r"(api[_-]?key|secret|refresh[_-]?token|access[_-]?token|session[_-]?token)"
            r"\s*[:=]\s*[\"'][A-Za-z0-9._~+/=-]{32,}[\"']",
            re.IGNORECASE,
        ),
    ]
    offenders = []

    for relative_name in result.stdout.splitlines():
        path = project_root / relative_name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in secret_patterns):
            offenders.append(relative_name)

    assert offenders == []

def test_web_package_and_vite_build_output_use_autotoken_paths():
    project_root = Path(__file__).resolve().parents[2]
    package_json = json.loads((project_root / "web" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((project_root / "web" / "package-lock.json").read_text(encoding="utf-8"))
    vite_config = (project_root / "web" / "vite.config.js").read_text(encoding="utf-8")

    assert package_json["name"] == "autotoken-web"
    assert package_lock["name"] == "autotoken-web"
    assert package_lock["packages"][""]["name"] == "autotoken-web"
    assert "../src/autotoken/web/dist" in vite_config
    assert "autoteam" not in vite_config.lower()

def test_built_web_dist_references_existing_autotoken_assets():
    project_root = Path(__file__).resolve().parents[2]
    dist_root = project_root / "src" / "autotoken" / "web" / "dist"
    index_html = dist_root / "index.html"

    assert index_html.is_file()
    html = index_html.read_text(encoding="utf-8")
    asset_paths = re.findall(r"""(?:src|href)=["']/(assets/[^"']+)["']""", html)

    assert asset_paths
    assert all((dist_root / asset_path).is_file() for asset_path in asset_paths)
    for path in [index_html, *(dist_root / asset_path for asset_path in asset_paths)]:
        assert "autoteam" not in path.read_text(encoding="utf-8", errors="ignore").lower()

def test_built_release_archives_exclude_removed_subsystem_markers():
    project_root = Path(__file__).resolve().parents[2]
    dist_root = project_root / "dist"
    wheel_path = dist_root / "autotoken-0.1.0-py3-none-any.whl"
    sdist_path = dist_root / "autotoken-0.1.0.tar.gz"
    canonical_sdist_root = PurePosixPath("autotoken-0.1.0")
    allowed_sdist_records = _allowed_removal_record_paths(canonical_sdist_root)
    assert wheel_path.is_file()
    assert sdist_path.is_file()

    assert {
        "wheel": _wheel_removed_subsystem_hits(wheel_path),
        "sdist": _sdist_removed_subsystem_hits(sdist_path, canonical_sdist_root, allowed_sdist_records),
    } == {"wheel": [], "sdist": []}

def test_built_python_artifacts_use_autotoken_metadata_and_minimal_legacy_package():
    project_root = Path(__file__).resolve().parents[2]
    dist_root = project_root / "dist"
    wheel_path = dist_root / "autotoken-0.1.0-py3-none-any.whl"
    sdist_path = dist_root / "autotoken-0.1.0.tar.gz"
    canonical_legacy_entrypoint_import = "from autotoken.interfaces.manager import main"
    expected_legacy_aliases = _autoteam_alias_mapping_from_text(
        (project_root / "src" / "autoteam" / "__init__.py").read_text(encoding="utf-8")
    )
    expected_protocol_bundle_files = _protocol_register_bundle_files(project_root)
    expected_oauth_extension_files = _oauth_helper_extension_files(project_root)
    expected_package_data_files = _autotoken_package_data_files(project_root)
    expected_oauth_manifest = json.loads(
        (project_root / "src" / "autotoken" / "oauth_helper_extension" / "manifest.json").read_text(encoding="utf-8")
    )

    assert wheel_path.is_file()
    assert sdist_path.is_file()

    with zipfile.ZipFile(wheel_path) as wheel:
        wheel_names = wheel.namelist()
        wheel_text_members = {}
        for name in wheel_names:
            try:
                wheel_text_members[name] = wheel.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
        legacy_package_files = sorted(name for name in wheel_names if name.startswith("autoteam/"))
        wheel_legacy_init = wheel.read("autoteam/__init__.py").decode("utf-8")
        wheel_legacy_entrypoint = wheel.read("autoteam/__main__.py").decode("utf-8")
        metadata = wheel.read("autotoken-0.1.0.dist-info/METADATA").decode("utf-8")
        entry_points = wheel.read("autotoken-0.1.0.dist-info/entry_points.txt").decode("utf-8")
        wheel_oauth_manifest = json.loads(wheel.read("autotoken/oauth_helper_extension/manifest.json").decode("utf-8"))
        wheel_web_html = wheel.read("autotoken/web/dist/index.html").decode("utf-8")
        wheel_web_names = sorted(name for name in wheel_names if name.startswith("autotoken/web/dist/"))

    assert legacy_package_files == ["autoteam/__init__.py", "autoteam/__main__.py"]
    assert _text_artifact_members_containing_old_name(wheel_text_members) == [
        "autoteam/__init__.py",
        "autoteam/__main__.py",
        "autotoken-0.1.0.dist-info/RECORD",
        "autotoken-0.1.0.dist-info/entry_points.txt",
        "autotoken/core/env.py",
        "autotoken/core/oauth_helper.py",
        "autotoken/oauth_helper_extension/content.js",
        "autotoken/storage/sqlite_store.py",
    ]
    assert _wheel_python_package_dirs_missing_init(wheel_names) == []
    assert (
        sorted(
            name.removeprefix("autotoken/_protocol_register/")
            for name in wheel_names
            if name.startswith("autotoken/_protocol_register/")
        )
        == expected_protocol_bundle_files
    )
    assert (
        sorted(
            name.removeprefix("autotoken/oauth_helper_extension/")
            for name in wheel_names
            if name.startswith("autotoken/oauth_helper_extension/")
        )
        == expected_oauth_extension_files
    )
    assert (
        sorted(
            name.removeprefix("autotoken/")
            for name in wheel_names
            if name.startswith("autotoken/")
            and not name.endswith(".py")
            and not name.endswith("/")
            and not name.startswith("autotoken/web/dist/")
        )
        == expected_package_data_files
    )
    assert wheel_oauth_manifest == expected_oauth_manifest
    assert "AutoToken" in wheel_oauth_manifest["name"]
    assert "AutoTeam" not in json.dumps(wheel_oauth_manifest)
    assert "autoteam" not in json.dumps(wheel_oauth_manifest).lower()
    assert _autoteam_alias_mapping_from_text(wheel_legacy_init) == expected_legacy_aliases
    assert canonical_legacy_entrypoint_import in wheel_legacy_entrypoint
    assert "autotoken.manager" not in wheel_legacy_entrypoint
    assert "Name: autotoken" in metadata
    assert "AutoTeam" not in metadata
    assert "AUTOTEAM" not in metadata
    assert "autotoken = autotoken.interfaces.manager:main" in entry_points
    assert "autoteam = autotoken.interfaces.manager:main" in entry_points
    wheel_web_assets = re.findall(r"""(?:src|href)=["']/(assets/[^"']+)["']""", wheel_web_html)
    assert wheel_web_assets
    assert all(f"autotoken/web/dist/{asset_path}" in wheel_names for asset_path in wheel_web_assets)
    assert any(name.endswith(".js") for name in wheel_web_names)
    assert any(name.endswith(".css") for name in wheel_web_names)
    assert "autoteam" not in wheel_web_html.lower()

    with tarfile.open(sdist_path) as sdist:
        sdist_names = sdist.getnames()
        sdist_text_members = {}
        for member in sdist.getmembers():
            if not member.isfile():
                continue
            if "/docs/plans/" in member.name or "/tests/" in member.name:
                continue
            member_file = sdist.extractfile(member)
            if member_file is None:
                continue
            try:
                sdist_text_members[member.name] = member_file.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
        sdist_legacy_init_file = sdist.extractfile("autotoken-0.1.0/src/autoteam/__init__.py")
        assert sdist_legacy_init_file is not None
        sdist_legacy_init = sdist_legacy_init_file.read().decode("utf-8")
        sdist_legacy_entrypoint_file = sdist.extractfile("autotoken-0.1.0/src/autoteam/__main__.py")
        assert sdist_legacy_entrypoint_file is not None
        sdist_legacy_entrypoint = sdist_legacy_entrypoint_file.read().decode("utf-8")
        sdist_oauth_manifest_file = sdist.extractfile(
            "autotoken-0.1.0/src/autotoken/oauth_helper_extension/manifest.json"
        )
        assert sdist_oauth_manifest_file is not None
        sdist_oauth_manifest = json.loads(sdist_oauth_manifest_file.read().decode("utf-8"))
        sdist_web_html_file = sdist.extractfile("autotoken-0.1.0/src/autotoken/web/dist/index.html")
        assert sdist_web_html_file is not None
        sdist_web_html = sdist_web_html_file.read().decode("utf-8")
        sdist_web_names = sorted(
            name for name in sdist_names if name.startswith("autotoken-0.1.0/src/autotoken/web/dist/")
        )

    assert sorted(name for name in sdist_names if "/src/autoteam/" in name) == [
        "autotoken-0.1.0/src/autoteam/__init__.py",
        "autotoken-0.1.0/src/autoteam/__main__.py",
    ]
    assert _text_artifact_members_containing_old_name(sdist_text_members) == [
        "autotoken-0.1.0/.gitignore",
        "autotoken-0.1.0/pyproject.toml",
        "autotoken-0.1.0/src/autoteam/__init__.py",
        "autotoken-0.1.0/src/autoteam/__main__.py",
        "autotoken-0.1.0/src/autotoken/core/env.py",
        "autotoken-0.1.0/src/autotoken/core/oauth_helper.py",
        "autotoken-0.1.0/src/autotoken/oauth_helper_extension/content.js",
        "autotoken-0.1.0/src/autotoken/storage/sqlite_store.py",
    ]
    assert (
        sorted(
            name.removeprefix("autotoken-0.1.0/src/autotoken/_protocol_register/")
            for name in sdist_names
            if name.startswith("autotoken-0.1.0/src/autotoken/_protocol_register/")
        )
        == expected_protocol_bundle_files
    )
    assert (
        sorted(
            name.removeprefix("autotoken-0.1.0/src/autotoken/oauth_helper_extension/")
            for name in sdist_names
            if name.startswith("autotoken-0.1.0/src/autotoken/oauth_helper_extension/")
        )
        == expected_oauth_extension_files
    )
    assert (
        sorted(
            name.removeprefix("autotoken-0.1.0/src/autotoken/")
            for name in sdist_names
            if name.startswith("autotoken-0.1.0/src/autotoken/")
            and not name.endswith(".py")
            and not name.startswith("autotoken-0.1.0/src/autotoken/web/dist/")
        )
        == expected_package_data_files
    )
    sdist_web_assets = re.findall(r"""(?:src|href)=["']/(assets/[^"']+)["']""", sdist_web_html)
    assert sdist_web_assets
    assert all(f"autotoken-0.1.0/src/autotoken/web/dist/{asset_path}" in sdist_names for asset_path in sdist_web_assets)
    assert any(name.endswith(".js") for name in sdist_web_names)
    assert any(name.endswith(".css") for name in sdist_web_names)
    assert "autoteam" not in sdist_web_html.lower()
    assert sdist_oauth_manifest == expected_oauth_manifest
    assert _autoteam_alias_mapping_from_text(sdist_legacy_init) == expected_legacy_aliases
    assert canonical_legacy_entrypoint_import in sdist_legacy_entrypoint
    assert "autotoken.manager" not in sdist_legacy_entrypoint
    assert sdist_names[0].startswith("autotoken-0.1.0/")

def test_built_wheel_supports_canonical_and_legacy_module_entrypoints(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    wheel_path = project_root / "dist" / "autotoken-0.1.0-py3-none-any.whl"
    checks = _autoteam_alias_mapping_from_text(
        (project_root / "src" / "autoteam" / "__init__.py").read_text(encoding="utf-8")
    )
    nested_module_suffixes = _nested_implementation_module_suffixes(project_root)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(wheel_path)

    import_result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import autoteam, autotoken, pathlib; "
                "print(autotoken.__name__); "
                "print(pathlib.Path(autotoken.__file__).as_posix()); "
                "print(autoteam is autotoken)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert import_result.returncode == 0, import_result.stdout
    import_lines = import_result.stdout.splitlines()
    assert import_lines[0] == "autotoken"
    assert "/dist/autotoken-0.1.0-py3-none-any.whl/autotoken/__init__.py" in import_lines[1]
    assert import_lines[2] == "True"

    submodule_result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import importlib
import sys

checks = {checks!r}

for legacy_suffix, canonical_name in checks.items():
    legacy_name = "autoteam." + legacy_suffix
    legacy_module = importlib.import_module(legacy_name)
    canonical_module = importlib.import_module(canonical_name)
    root_wrapper_name = "autotoken." + legacy_suffix
    assert legacy_module is canonical_module, (legacy_name, legacy_module, canonical_module)
    assert root_wrapper_name not in sys.modules, (legacy_name, root_wrapper_name)
""",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert submodule_result.returncode == 0, submodule_result.stdout

    root_alias_metadata_result = subprocess.run(
        [
            sys.executable,
            "-c",
            _legacy_root_alias_metadata_check_script(checks),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert root_alias_metadata_result.returncode == 0, root_alias_metadata_result.stdout

    package_metadata_result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib

package_suffixes = [
    "_protocol_register",
    "api_routes",
    "auth",
    "core",
    "interfaces",
    "payments",
    "storage",
]

for suffix in package_suffixes:
    legacy_module = importlib.import_module("autoteam." + suffix)
    canonical_name = "autotoken." + suffix
    canonical_module = importlib.import_module(canonical_name)
    assert legacy_module is canonical_module, (suffix, legacy_module, canonical_module)
    assert legacy_module.__name__ == canonical_name, (suffix, legacy_module.__name__)
    assert legacy_module.__package__ == canonical_name, (suffix, legacy_module.__package__)
    assert legacy_module.__spec__.name == canonical_name, (suffix, legacy_module.__spec__.name)
    assert list(legacy_module.__path__) == list(canonical_module.__path__), suffix
""",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert package_metadata_result.returncode == 0, package_metadata_result.stdout

    nested_spec_result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import importlib.util

module_suffixes = {nested_module_suffixes!r}
offenders = []

for module_suffix in module_suffixes:
    legacy_spec = importlib.util.find_spec("autoteam." + module_suffix)
    canonical_spec = importlib.util.find_spec("autotoken." + module_suffix)
    legacy_origin = getattr(legacy_spec, "origin", None)
    canonical_origin = getattr(canonical_spec, "origin", None)
    if legacy_origin != canonical_origin:
        offenders.append((module_suffix, legacy_origin, canonical_origin))

assert offenders == [], offenders
""",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert nested_spec_result.returncode == 0, nested_spec_result.stdout

    for module_name in ("autotoken", "autoteam"):
        module_result = subprocess.run(
            [sys.executable, "-m", module_name, "--help"],
            cwd=tmp_path,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )

        assert module_result.returncode == 0, module_result.stdout
        assert module_result.stdout.startswith("usage: autotoken ")
        assert "manager.py" not in module_result.stdout
        assert "api" in module_result.stdout
