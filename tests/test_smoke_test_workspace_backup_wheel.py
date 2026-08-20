from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import smoke_test_workspace_backup_wheel


def test_main_invokes_workspace_backup_smoke_with_cli_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"
    observed: list[tuple[Path, Path]] = []

    def fake_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        observed.append((suite_wheel, core_wheel))

    monkeypatch.setattr(
        smoke_test_workspace_backup_wheel,
        "smoke_test_workspace_backup_wheel",
        fake_smoke,
    )

    assert smoke_test_workspace_backup_wheel.main((str(suite), str(core))) == 0
    assert observed == [(suite, core)]
    assert capsys.readouterr().out.strip() == (
        "Workspace backup wheel smoke test passed."
    )


def test_main_returns_failure_when_workspace_backup_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"

    def fail_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        del suite_wheel, core_wheel
        raise smoke_test_workspace_backup_wheel.WorkspaceBackupSmokeTestError(
            "synthetic failure"
        )

    monkeypatch.setattr(
        smoke_test_workspace_backup_wheel,
        "smoke_test_workspace_backup_wheel",
        fail_smoke,
    )

    assert smoke_test_workspace_backup_wheel.main((str(suite), str(core))) == 1
    assert "synthetic failure" in capsys.readouterr().err


def test_isolated_command_env_removes_workspace_and_pythonpath_variants(
    tmp_path: Path,
) -> None:
    result = smoke_test_workspace_backup_wheel._isolated_command_env(
        {
            "PATH": "synthetic",
            "PYTHONPATH": "source-a",
            "PythonPath": "source-b",
            "PDS_WORKSPACE_ROOT": "real-workspace",
        },
        user_home=tmp_path / "user",
    )

    assert result["PATH"] == "synthetic"
    assert all(key.upper() != "PYTHONPATH" for key in result)
    assert all(key.upper() != "PDS_WORKSPACE_ROOT" for key in result)
    assert result["PYTHONNOUSERSITE"] == "1"
    assert result["HOME"] == str(tmp_path / "user")
    assert result["USERPROFILE"] == str(tmp_path / "user")


def test_snapshot_tree_preserves_empty_hidden_binary_and_zero_byte_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    (root / "nested" / "empty").mkdir(parents=True)
    (root / ".hidden").write_text("hidden", encoding="utf-8")
    (root / "nested" / "opaque.bin").write_bytes(b"\x00\xff")
    (root / "zero.dat").write_bytes(b"")

    snapshot = smoke_test_workspace_backup_wheel._snapshot_tree(root)

    assert snapshot.directories == ("nested", "nested/empty")
    assert tuple(item.path for item in snapshot.files) == (
        ".hidden",
        "nested/opaque.bin",
        "zero.dat",
    )
    assert tuple(item.size for item in snapshot.files) == (6, 2, 0)


def test_manifest_assertion_rejects_absolute_source_path_leak(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    final = tmp_path / "backup" / "pds-workspace-backup-20260820T190102345678Z"
    final.mkdir(parents=True)
    manifest = final / "manifest.json"
    payload = {
        "record_type": "pds_workspace_backup_manifest",
        "schema_version": "1",
        "backup_id": final.name,
        "created_at": "2026-08-20T19:01:02.345678Z",
        "suite_version": "0.1.0.dev0",
        "core_version": "0.6.0",
        "payload_root": "workspace",
        "hash_algorithm": "sha256",
        "directory_count": 0,
        "file_count": 0,
        "total_bytes": 0,
        "directories": [],
        "files": [],
        "exclusions": [],
        "source": str(source.resolve()),
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        smoke_test_workspace_backup_wheel.WorkspaceBackupSmokeTestError,
        match="absolute source workspace path",
    ):
        smoke_test_workspace_backup_wheel._assert_manifest_matches_source(
            manifest,
            source_root=source,
            final_root=final,
            source=smoke_test_workspace_backup_wheel.TreeSnapshot((), ()),
        )
