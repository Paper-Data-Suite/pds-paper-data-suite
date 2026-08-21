from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import paper_data_suite.cli as cli_module
import paper_data_suite.workspace_backup_cli as backup_cli_module
from paper_data_suite.cli import build_parser
from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    WorkspaceBackupManifest,
)
from paper_data_suite.workspace_backup_verification import (
    WorkspaceBackupVerificationResult,
)
from paper_data_suite.workspace_restore import (
    WorkspaceRestoreDestinationError,
    WorkspaceRestorePlan,
    WorkspaceRestoreResult,
)

FIXED_TIME = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)
BACKUP_ID = "pds-workspace-backup-20260820T174812123456Z"


def _manifest() -> WorkspaceBackupManifest:
    return WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=BACKUP_ID,
        created_at=FIXED_TIME,
        suite_version="0.1.0",
        core_version="0.6.0",
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=0,
        file_count=0,
        total_bytes=0,
        directories=(),
        files=(),
        exclusions=(),
    )


def _plan(tmp_path: Path) -> WorkspaceRestorePlan:
    backup = tmp_path / BACKUP_ID
    verification = WorkspaceBackupVerificationResult(
        backup_root=backup,
        manifest=_manifest(),
        manifest_sha256="a" * 64,
    )
    return WorkspaceRestorePlan(
        verification=verification,
        workspace_root=tmp_path / "active",
        workspace_source="saved_config",
        destination_root=tmp_path / "restored",
        destination_parent=tmp_path,
        destination_anchor=tmp_path,
        destination_free_bytes=10**9,
        required_free_bytes=64 * 1024 * 1024,
        destination_parent_exists=True,
    )


def test_restore_parser_requires_explicit_backup_and_destination() -> None:
    parser = build_parser()
    arguments = parser.parse_args(
        [
            "backup",
            "restore",
            "backup-root",
            "--destination",
            "restored-root",
            "--yes",
        ]
    )

    assert arguments.command == "backup"
    assert arguments.backup_command == "restore"
    assert arguments.backup == Path("backup-root")
    assert arguments.destination == Path("restored-root")
    assert arguments.yes is True


def test_restore_cancel_is_noop(tmp_path: Path, monkeypatch, capsys) -> None:
    plan = _plan(tmp_path)
    calls = 0

    monkeypatch.setattr(
        backup_cli_module,
        "plan_workspace_restore",
        lambda _backup, _destination: plan,
    )

    def should_not_restore(_plan: WorkspaceRestorePlan) -> WorkspaceRestoreResult:
        nonlocal calls
        calls += 1
        raise AssertionError("restore must not execute after cancellation")

    monkeypatch.setattr(
        backup_cli_module,
        "restore_workspace_backup",
        should_not_restore,
    )

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        input_fn=lambda _prompt: "Q",
    )

    assert result == 0
    assert calls == 0
    output = capsys.readouterr()
    assert "No restore destination has been created yet." in output.out
    assert "Workspace restore cancelled." in output.out


@pytest.mark.parametrize("exception_type", (EOFError, KeyboardInterrupt))
def test_restore_eof_or_interrupt_cancels(
    tmp_path: Path,
    monkeypatch,
    capsys,
    exception_type,
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        backup_cli_module,
        "plan_workspace_restore",
        lambda _backup, _destination: plan,
    )

    def interrupted(_prompt: str) -> str:
        raise exception_type()

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        input_fn=interrupted,
    )

    assert result == 0
    assert "Workspace restore cancelled." in capsys.readouterr().out


def test_restore_requires_exact_uppercase_confirmation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        backup_cli_module,
        "plan_workspace_restore",
        lambda _backup, _destination: plan,
    )
    monkeypatch.setattr(
        backup_cli_module,
        "restore_workspace_backup",
        lambda reviewed: WorkspaceRestoreResult(
            destination_root=reviewed.destination_root,
            manifest=reviewed.verification.manifest,
            manifest_sha256=reviewed.manifest_sha256,
        ),
    )
    responses = iter(("restore", "RESTORE"))

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        input_fn=lambda _prompt: next(responses),
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Enter exact uppercase RESTORE" in output
    assert "Workspace restore complete" in output


def test_restore_yes_bypasses_prompt_only_and_reports_selection_boundary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    plan = _plan(tmp_path)
    restored = WorkspaceRestoreResult(
        destination_root=plan.destination_root,
        manifest=plan.verification.manifest,
        manifest_sha256=plan.manifest_sha256,
    )
    monkeypatch.setattr(
        backup_cli_module,
        "plan_workspace_restore",
        lambda _backup, _destination: plan,
    )
    monkeypatch.setattr(
        backup_cli_module,
        "restore_workspace_backup",
        lambda reviewed: restored if reviewed is plan else None,
    )

    def prompt_must_not_run(_prompt: str) -> str:
        raise AssertionError("--yes must bypass only the interactive prompt")

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        assume_yes=True,
        input_fn=prompt_must_not_run,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "The currently resolved workspace was not changed." in output
    assert "The restored workspace was not selected automatically." in output
    assert "pds workspace show" in output
    assert "pds workspace set" in output


def test_restore_plan_failure_is_bounded(monkeypatch, capsys) -> None:
    def refuse(_backup: Path, _destination: Path) -> WorkspaceRestorePlan:
        raise WorkspaceRestoreDestinationError("destination already exists")

    monkeypatch.setattr(backup_cli_module, "plan_workspace_restore", refuse)

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        assume_yes=True,
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "Restore refused:" in error
    assert "destination already exists" in error


def test_restore_execution_failure_is_bounded(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        backup_cli_module,
        "plan_workspace_restore",
        lambda _backup, _destination: plan,
    )

    def fail(_plan: WorkspaceRestorePlan) -> WorkspaceRestoreResult:
        raise WorkspaceRestoreDestinationError("changed after confirmation")

    monkeypatch.setattr(backup_cli_module, "restore_workspace_backup", fail)

    result = backup_cli_module.run_workspace_backup_restore(
        Path("backup"),
        Path("destination"),
        assume_yes=True,
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "Restore failed:" in error
    assert "changed after confirmation" in error


def test_main_dispatches_restore(monkeypatch) -> None:
    seen: list[tuple[Path, Path, bool]] = []

    def run(backup: Path, destination: Path, *, assume_yes: bool = False) -> int:
        seen.append((backup, destination, assume_yes))
        return 17

    monkeypatch.setattr(cli_module, "run_workspace_backup_restore", run)

    result = cli_module.main(
        [
            "backup",
            "restore",
            "backup-root",
            "--destination",
            "restored-root",
            "--yes",
        ]
    )

    assert result == 17
    assert seen == [(Path("backup-root"), Path("restored-root"), True)]
