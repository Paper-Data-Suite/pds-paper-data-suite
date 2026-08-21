from __future__ import annotations

from pathlib import Path

import pytest

from scripts import smoke_test_workspace_restore_wheel


def test_main_invokes_workspace_restore_smoke_with_cli_paths(
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
        smoke_test_workspace_restore_wheel,
        "smoke_test_workspace_restore_wheel",
        fake_smoke,
    )

    assert smoke_test_workspace_restore_wheel.main((str(suite), str(core))) == 0
    assert observed == [(suite, core)]
    assert capsys.readouterr().out.strip() == (
        "Workspace restore wheel smoke test passed."
    )


def test_main_returns_failure_when_workspace_restore_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite.whl"
    core = tmp_path / "core.whl"

    def fail_smoke(suite_wheel: Path, core_wheel: Path) -> None:
        del suite_wheel, core_wheel
        raise smoke_test_workspace_restore_wheel.WorkspaceRestoreSmokeTestError(
            "synthetic failure"
        )

    monkeypatch.setattr(
        smoke_test_workspace_restore_wheel,
        "smoke_test_workspace_restore_wheel",
        fail_smoke,
    )

    assert smoke_test_workspace_restore_wheel.main((str(suite), str(core))) == 1
    assert "synthetic failure" in capsys.readouterr().err


def test_isolated_command_env_removes_workspace_and_pythonpath_variants(
    tmp_path: Path,
) -> None:
    result = smoke_test_workspace_restore_wheel._isolated_command_env(
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


def test_snapshot_tree_preserves_empty_hidden_binary_unicode_and_zero(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    (root / "nested" / "empty").mkdir(parents=True)
    (root / ".hidden").write_text("hidden", encoding="utf-8")
    (root / "nested" / "opaque.bin").write_bytes(b"\x00\xff")
    (root / "unicodé.txt").write_text("ok", encoding="utf-8")
    (root / "zero.dat").write_bytes(b"")

    snapshot = smoke_test_workspace_restore_wheel._snapshot_tree(root)

    assert snapshot.directories == ("nested", "nested/empty")
    assert tuple(item.path for item in snapshot.files) == (
        ".hidden",
        "nested/opaque.bin",
        "unicodé.txt",
        "zero.dat",
    )
    assert tuple(item.size for item in snapshot.files) == (6, 2, 2, 0)


def test_verify_help_assertion_requires_integrity_boundary() -> None:
    good = (
        "Verify manifest SHA-256 without modifying a backup; "
        "this is not a runtime-compatibility guarantee."
    )
    smoke_test_workspace_restore_wheel._assert_verify_help(good)

    argparse_wrapped = (
        "Verify manifest SHA-256 without modifying a backup; "
        "this is not a runtime-\ncompatibility guarantee."
    )
    smoke_test_workspace_restore_wheel._assert_verify_help(argparse_wrapped)

    with pytest.raises(
        smoke_test_workspace_restore_wheel.WorkspaceRestoreSmokeTestError,
        match="verify help",
    ):
        smoke_test_workspace_restore_wheel._assert_verify_help(
            "verify a backup"
        )


def test_restore_help_assertion_requires_selection_and_destination_boundary() -> None:
    good = (
        "Restore to --destination which must not already exist; use --yes. "
        "The restored workspace is not selected automatically."
    )
    smoke_test_workspace_restore_wheel._assert_restore_help(good)

    with pytest.raises(
        smoke_test_workspace_restore_wheel.WorkspaceRestoreSmokeTestError,
        match="restore help",
    ):
        smoke_test_workspace_restore_wheel._assert_restore_help(
            "restore a backup"
        )
