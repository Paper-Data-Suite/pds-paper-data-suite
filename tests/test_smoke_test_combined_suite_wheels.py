from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import smoke_test_combined_suite_wheels as combined


def test_current_manifest_drives_expected_launchable_composition() -> None:
    applications = combined._application_expectations()

    assert tuple(item.component_id for item in applications) == (
        "concord",
        "quillan",
        "scoreform",
        "vitrine",
    )
    assert tuple(item.version for item in applications) == (
        "0.2.0",
        "0.9.0",
        "0.10.0",
        "0.2.0",
    )


def test_workspace_snapshot_tracks_empty_directories_and_file_bytes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    empty = workspace / "future" / "empty"
    empty.mkdir(parents=True)
    payload = workspace / "future" / "payload.bin"
    payload.write_bytes(b"alpha")

    first = combined._snapshot_tree(workspace)
    payload.write_bytes(b"bravo")
    second = combined._snapshot_tree(workspace)

    assert ("future/empty", "directory") in first
    assert first != second


def test_workspace_snapshot_rejects_symlink_when_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(combined.CombinedSuiteSmokeError, match="symlink"):
        combined._snapshot_tree(workspace)


def test_suite_settings_path_matches_windows_and_xdg_contract(tmp_path: Path) -> None:
    home = tmp_path / "home"
    windows_root = tmp_path / "local"
    xdg_root = tmp_path / "xdg"

    windows = combined._suite_settings_path(
        home,
        {"LOCALAPPDATA": str(windows_root)},
        platform="win32",
    )
    linux = combined._suite_settings_path(
        home,
        {"XDG_CONFIG_HOME": str(xdg_root)},
        platform="linux",
    )

    assert windows == windows_root / "Paper Data Suite" / "settings.json"
    assert linux == xdg_root / "paper-data-suite" / "settings.json"


def test_settings_document_accepts_only_privacy_minimized_schema(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "record_type": "paper_data_suite_settings",
                "schema_version": "1",
                "recent_components": ["vitrine", "scoreform"],
            }
        ),
        encoding="utf-8",
    )

    combined._assert_settings_document(
        settings,
        expected_recent=("vitrine", "scoreform"),
    )

    settings.write_text(
        json.dumps(
            {
                "record_type": "paper_data_suite_settings",
                "schema_version": "1",
                "recent_components": [],
                "student_id": "student001",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(combined.CombinedSuiteSmokeError, match="unexpected fields"):
        combined._assert_settings_document(settings, expected_recent=())


def test_sibling_private_import_audit_detects_direct_module_import(
    tmp_path: Path,
) -> None:
    package = tmp_path / "paper_data_suite"
    package.mkdir()
    (package / "bad.py").write_text(
        "from concord.private_bits import secret\n",
        encoding="utf-8",
    )

    findings = combined._sibling_private_imports(package)

    assert len(findings) == 1
    assert "concord.private_bits" in findings[0]


def test_current_suite_package_has_no_sibling_private_imports() -> None:
    assert combined._sibling_private_imports(Path("paper_data_suite")) == ()


def test_combined_setup_inputs_preserve_reviewed_explicit_values(
    tmp_path: Path,
) -> None:
    roster = tmp_path / "synthetic-roster.csv"

    first = combined._first_setup_input(roster).splitlines()
    rerun = combined._rerun_setup_input(roster).splitlines()

    assert first[0] == "2026-2027"
    assert first[1:3] == ["eng10", str(roster)]
    assert "njsls_ela_2023" in first
    assert "quarter" in first
    assert "Quarter 1" in first
    assert first[-1] == "APPLY"
    assert rerun == [
        "eng10",
        str(roster),
        "",
        "njsls_ela_2023",
        "APPLY",
    ]


def test_opaque_custody_fixture_is_neutral_and_snapshot_visible(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    combined._seed_opaque_workspace_fixture(workspace)
    snapshot = combined._snapshot_tree(workspace)

    assert (
        "future-module/opaque-custody-fixture/empty",
        "directory",
    ) in snapshot
    assert any(
        path == "future-module/opaque-custody-fixture/opaque.bin"
        and value.startswith("file:")
        for path, value in snapshot
    )
    assert any(
        path == "future-module/opaque-custody-fixture/zero.dat"
        and value.startswith("file:0:")
        for path, value in snapshot
    )


def test_completed_backup_discovery_rejects_ambiguous_results(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    first = parent / "pds-workspace-backup-20260823T120000000000Z"
    first.mkdir()

    assert combined._find_completed_backup(parent) == first

    (parent / "pds-workspace-backup-20260823T120001000000Z").mkdir()
    with pytest.raises(combined.CombinedSuiteSmokeError, match="Expected one"):
        combined._find_completed_backup(parent)


def test_backup_manifest_check_qualifies_suite_and_core_provenance(
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "pds-workspace-backup-20260823T120000000000Z"
    backup_root.mkdir()
    manifest_path = backup_root / "manifest.json"
    snapshot: combined.TreeSnapshot = (
        ("future", "directory"),
        ("future/payload.bin", "file:5:" + "0" * 64),
    )
    manifest = combined.load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if component.component_id == "core"
    )
    manifest_path.write_text(
        json.dumps(
            {
                "record_type": "pds_workspace_backup_manifest",
                "schema_version": "1",
                "backup_id": backup_root.name,
                "created_at": "2026-08-23T12:00:00+00:00",
                "suite_version": manifest.suite.version,
                "core_version": core.version,
                "payload_root": "workspace",
                "hash_algorithm": "sha256",
                "directory_count": 1,
                "file_count": 1,
                "total_bytes": 5,
                "directories": ["future"],
                "files": [],
                "exclusions": [],
            }
        ),
        encoding="utf-8",
    )

    digest = combined._assert_backup_manifest(
        manifest_path,
        backup_root=backup_root,
        source_snapshot=snapshot,
    )

    assert len(digest) == 64


def test_workspace_override_environment_is_explicit_and_nonmutating(
    tmp_path: Path,
) -> None:
    original = {"HOME": str(tmp_path / "home"), "PDS_WORKSPACE_ROOT": "old"}
    restored = tmp_path / "restored"

    override = combined._workspace_override_environment(original, restored)

    assert override["PDS_WORKSPACE_ROOT"] == str(restored.resolve())
    assert original["PDS_WORKSPACE_ROOT"] == "old"
    assert override["HOME"] == original["HOME"]
