from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    BackupSourceFile,
    WorkspaceBackupDestinationError,
    WorkspaceBackupInventory,
    WorkspaceBackupManifest,
    WorkspaceBackupPlan,
    WorkspaceBackupResult,
    WorkspaceBackupVerificationError,
)
from paper_data_suite.workspace_backup_cli import (
    render_workspace_backup_plan,
    render_workspace_backup_result,
    run_workspace_backup_create,
)


def _plan(tmp_path: Path) -> WorkspaceBackupPlan:
    created = datetime(2026, 8, 20, 18, 45, 1, 123456, tzinfo=timezone.utc)
    inventory = WorkspaceBackupInventory(
        directories=("classes", "empty"),
        files=(BackupSourceFile("classes/student-private.csv", 12),),
        total_bytes=12,
    )
    return WorkspaceBackupPlan(
        workspace_root=tmp_path / "workspace",
        workspace_source="saved_config",
        destination_parent=tmp_path / "backups",
        final_backup_root=(
            tmp_path / "backups" / "pds-workspace-backup-20260820T184501123456Z"
        ),
        backup_id="pds-workspace-backup-20260820T184501123456Z",
        created_at=created,
        suite_version="0.1.0.dev0",
        core_version="0.6.0",
        inventory=inventory,
        destination_free_bytes=100_000_000,
        required_free_bytes=67_108_876,
        destination_parent_exists=True,
    )


def _result(plan: WorkspaceBackupPlan) -> WorkspaceBackupResult:
    manifest = WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=plan.backup_id,
        created_at=plan.created_at,
        suite_version=plan.suite_version,
        core_version=plan.core_version,
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=2,
        file_count=1,
        total_bytes=12,
        directories=("classes", "empty"),
        files=(BackupFileEntry("classes/student-private.csv", 12, "a" * 64),),
        exclusions=(),
    )
    return WorkspaceBackupResult(
        final_backup_root=plan.final_backup_root,
        manifest=manifest,
        manifest_sha256="b" * 64,
    )


def test_render_plan_is_bounded_and_privacy_explicit(tmp_path: Path) -> None:
    output = render_workspace_backup_plan(_plan(tmp_path))
    assert "saved workspace selection" in output
    assert "Directories: 2" in output
    assert "Files: 1" in output
    assert "Minimum required free bytes" in output
    assert "potentially sensitive" in output
    assert "does not encrypt, upload, or cloud-sync" in output
    assert "student-private.csv" not in output
    assert "No backup has been created yet." in output


def test_render_result_is_bounded_and_explains_hash_limit(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    output = render_workspace_backup_result(plan, _result(plan))
    assert "Workspace backup complete" in output
    assert f"Backup: {plan.final_backup_root}" in output
    assert "Manifest SHA-256: " + "b" * 64 in output
    assert "does not encrypt or authenticate" in output
    assert "student-private.csv" not in output


def test_interactive_q_cancels_before_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    plan = _plan(tmp_path)
    monkeypatch.setattr(cli, "plan_workspace_backup", lambda _destination: plan)
    monkeypatch.setattr(
        cli,
        "create_workspace_backup",
        lambda _plan: pytest.fail("creator must not run on cancellation"),
    )
    assert run_workspace_backup_create(
        tmp_path / "backups", input_fn=lambda _prompt: "Q"
    ) == 0
    assert "No backup was created" in capsys.readouterr().out


def test_confirmation_requires_exact_uppercase_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    plan = _plan(tmp_path)
    responses = iter(("backup", "Q"))
    monkeypatch.setattr(cli, "plan_workspace_backup", lambda _destination: plan)
    monkeypatch.setattr(
        cli,
        "create_workspace_backup",
        lambda _plan: pytest.fail("lowercase backup must not authorize creation"),
    )
    assert run_workspace_backup_create(
        tmp_path / "backups", input_fn=lambda _prompt: next(responses)
    ) == 0
    output = capsys.readouterr().out
    assert "exact uppercase BACKUP" in output
    assert "No backup was created" in output


def test_exact_backup_authorizes_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    plan = _plan(tmp_path)
    result = _result(plan)
    calls: list[WorkspaceBackupPlan] = []
    monkeypatch.setattr(cli, "plan_workspace_backup", lambda _destination: plan)

    def create(received: WorkspaceBackupPlan) -> WorkspaceBackupResult:
        calls.append(received)
        return result

    monkeypatch.setattr(cli, "create_workspace_backup", create)
    assert run_workspace_backup_create(
        tmp_path / "backups", input_fn=lambda _prompt: "BACKUP"
    ) == 0
    assert calls == [plan]
    assert "Workspace backup complete" in capsys.readouterr().out


def test_yes_bypasses_prompt_but_still_renders_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    plan = _plan(tmp_path)
    result = _result(plan)
    monkeypatch.setattr(cli, "plan_workspace_backup", lambda _destination: plan)
    monkeypatch.setattr(cli, "create_workspace_backup", lambda _plan: result)

    def no_input(_prompt: str) -> str:
        raise AssertionError("--yes must bypass interactive input")

    assert run_workspace_backup_create(
        tmp_path / "backups", assume_yes=True, input_fn=no_input
    ) == 0
    output = capsys.readouterr().out
    assert "No backup has been created yet." in output
    assert "Workspace backup complete" in output


def test_preflight_failure_is_refused_without_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    monkeypatch.setattr(
        cli,
        "plan_workspace_backup",
        lambda _destination: (_ for _ in ()).throw(
            WorkspaceBackupDestinationError("destination is inside workspace")
        ),
    )
    monkeypatch.setattr(
        cli,
        "create_workspace_backup",
        lambda _plan: pytest.fail("creator must not run after preflight refusal"),
    )
    assert run_workspace_backup_create(tmp_path / "bad", assume_yes=True) == 1
    assert "Backup refused: destination is inside workspace" in capsys.readouterr().err


def test_creation_failure_is_reported_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import paper_data_suite.workspace_backup_cli as cli

    plan = _plan(tmp_path)
    monkeypatch.setattr(cli, "plan_workspace_backup", lambda _destination: plan)
    monkeypatch.setattr(
        cli,
        "create_workspace_backup",
        lambda _plan: (_ for _ in ()).throw(
            WorkspaceBackupVerificationError("copied bytes do not match")
        ),
    )
    assert run_workspace_backup_create(tmp_path / "backups", assume_yes=True) == 1
    assert "Backup failed: copied bytes do not match" in capsys.readouterr().err
