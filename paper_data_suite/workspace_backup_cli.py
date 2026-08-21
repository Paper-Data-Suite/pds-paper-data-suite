"""Teacher-facing command orchestration for whole-workspace backup creation."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from paper_data_suite.compatibility import CompatibilityManifestError
from paper_data_suite.workspace_backup import (
    WorkspaceBackupError,
    WorkspaceBackupPlan,
    WorkspaceBackupResult,
    create_workspace_backup,
    plan_workspace_backup,
)
from paper_data_suite.workspace_backup_verification import (
    WorkspaceBackupVerificationResult,
    verify_workspace_backup,
)
from paper_data_suite.workspace_cli import workspace_source_label
from paper_data_suite.workspace_restore import (
    WorkspaceRestoreError,
    WorkspaceRestorePlan,
    WorkspaceRestoreResult,
    plan_workspace_restore,
    restore_workspace_backup,
)
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    CoreWorkspaceServiceError,
)

InputReader = Callable[[str], str]


def _read(prompt: str, input_fn: InputReader) -> str | None:
    try:
        return input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def render_workspace_backup_plan(plan: WorkspaceBackupPlan) -> str:
    """Render one bounded read-only backup preview without listing payload paths."""
    lines = [
        "Paper Data Suite workspace backup",
        "",
        f"Resolved workspace: {plan.workspace_root}",
        f"Workspace source: {workspace_source_label(plan.workspace_source)}",
        f"Destination parent: {plan.destination_parent}",
        f"Proposed backup: {plan.final_backup_root}",
        f"Directories: {plan.inventory.directory_count}",
        f"Files: {plan.inventory.file_count}",
        f"Payload bytes: {plan.inventory.total_bytes}",
        f"Destination free bytes: {plan.destination_free_bytes}",
        f"Minimum required free bytes: {plan.required_free_bytes}",
        "Backup format: pds_workspace_backup_manifest v1",
        "",
        "Privacy warning:",
        "  This backup contains the same potentially sensitive classroom/student",
        "  data as the workspace. Store it only in an appropriate teacher-controlled",
        "  or institutionally approved location.",
        "  PDS does not encrypt, upload, or cloud-sync this backup.",
        "",
        "No backup has been created yet.",
    ]
    return "\n".join(lines) + "\n"


def render_workspace_backup_result(
    plan: WorkspaceBackupPlan,
    result: WorkspaceBackupResult,
) -> str:
    """Render a bounded completion summary for one verified published backup."""
    manifest = result.manifest
    lines = [
        "Workspace backup complete",
        "",
        f"Source workspace: {plan.workspace_root}",
        f"Backup: {result.final_backup_root}",
        f"Directories: {manifest.directory_count}",
        f"Files: {manifest.file_count}",
        f"Payload bytes: {manifest.total_bytes}",
        f"Created at: {manifest.created_at}",
        f"Manifest SHA-256: {result.manifest_sha256}",
        "",
        "SHA-256 supports integrity checking; it does not encrypt or authenticate",
        "the backup.",
    ]
    return "\n".join(lines) + "\n"


def render_workspace_backup_verification_result(
    result: WorkspaceBackupVerificationResult,
) -> str:
    """Render one bounded completed-backup integrity result."""
    manifest = result.manifest
    lines = [
        "Workspace backup verified",
        "",
        f"Backup: {result.backup_root}",
        f"Backup ID: {manifest.backup_id}",
        f"Created at: {manifest.created_at}",
        f"Recorded suite version: {manifest.suite_version}",
        f"Recorded Core version: {manifest.core_version}",
        f"Directories: {manifest.directory_count}",
        f"Files: {manifest.file_count}",
        f"Payload bytes: {manifest.total_bytes}",
        f"Manifest SHA-256: {result.manifest_sha256}",
        "",
        "The manifest and payload agree byte-for-byte with backup format v1.",
        "SHA-256 verifies integrity against this manifest; it is not a",
        "digital signature and does not prove who created the backup.",
    ]
    return "\n".join(lines) + "\n"


def run_workspace_backup_verify(backup: Path) -> int:
    """Independently verify one completed workspace backup."""
    try:
        result = verify_workspace_backup(backup)
    except (WorkspaceBackupError, OSError) as error:
        message = str(error)[:500] or error.__class__.__name__
        print(f"Backup verification failed: {message}", file=sys.stderr)
        return 1
    print(render_workspace_backup_verification_result(result), end="")
    return 0


def render_workspace_restore_plan(plan: WorkspaceRestorePlan) -> str:
    """Render one bounded verified restore preview."""
    manifest = plan.verification.manifest
    lines = [
        "Paper Data Suite workspace restore",
        "",
        f"Backup: {plan.backup_root}",
        f"Backup ID: {manifest.backup_id}",
        f"Backup created at: {manifest.created_at}",
        f"Recorded suite version: {manifest.suite_version}",
        f"Recorded Core version: {manifest.core_version}",
        f"Manifest SHA-256: {plan.manifest_sha256}",
        f"Directories: {manifest.directory_count}",
        f"Files: {manifest.file_count}",
        f"Payload bytes: {manifest.total_bytes}",
        f"Currently resolved workspace: {plan.workspace_root}",
        f"Workspace source: {workspace_source_label(plan.workspace_source)}",
        f"Restore destination: {plan.destination_root}",
        f"Destination free bytes: {plan.destination_free_bytes}",
        f"Minimum required free bytes: {plan.required_free_bytes}",
        "",
        "Privacy warning:",
        "  The restored workspace contains the same potentially sensitive",
        "  classroom/student data as the backup. Store it only in an appropriate",
        "  teacher-controlled or institutionally approved location.",
        "",
        "The currently resolved workspace will not be modified.",
        "The restored workspace will not be selected automatically.",
        "No restore destination has been created yet.",
    ]
    return "\n".join(lines) + "\n"


def render_workspace_restore_result(
    plan: WorkspaceRestorePlan,
    result: WorkspaceRestoreResult,
) -> str:
    """Render a bounded completion summary for one published restore."""
    manifest = result.manifest
    lines = [
        "Workspace restore complete",
        "",
        f"Backup ID: {manifest.backup_id}",
        f"Source backup: {plan.backup_root}",
        f"Restore destination: {result.destination_root}",
        f"Directories: {manifest.directory_count}",
        f"Files: {manifest.file_count}",
        f"Payload bytes: {manifest.total_bytes}",
        f"Manifest SHA-256: {result.manifest_sha256}",
        "",
        "The currently resolved workspace was not changed.",
        "The restored workspace was not selected automatically.",
        "To review current selection, run: pds workspace show",
        (
            "To select this restored workspace later, run: "
            f'pds workspace set "{result.destination_root}"'
        ),
        "",
        "Byte-perfect restoration does not itself prove runtime/schema",
        "compatibility with the currently installed suite or modules.",
    ]
    return "\n".join(lines) + "\n"


def _cancel_restore() -> int:
    print("Workspace restore cancelled. No restore destination was created.")
    return 0


def _confirm_restore(input_fn: InputReader) -> bool:
    while True:
        choice = _read(
            "Type RESTORE to create the alternate restored workspace, or Q to cancel: ",
            input_fn,
        )
        if choice is None or choice == "Q":
            return False
        if choice == "RESTORE":
            return True
        print("Enter exact uppercase RESTORE to continue, or Q to cancel.")


def run_workspace_backup_restore(
    backup: Path,
    destination: Path,
    *,
    assume_yes: bool = False,
    input_fn: InputReader = input,
) -> int:
    """Verify, preview, confirm, and restore to a new alternate location."""
    try:
        plan = plan_workspace_restore(backup, destination)
    except (
        CompatibilityManifestError,
        CoreWorkspaceQualificationError,
        CoreWorkspaceServiceError,
        WorkspaceBackupError,
        WorkspaceRestoreError,
        OSError,
    ) as error:
        message = str(error)[:500] or error.__class__.__name__
        print(f"Restore refused: {message}", file=sys.stderr)
        return 1

    print(render_workspace_restore_plan(plan), end="")
    if not assume_yes and not _confirm_restore(input_fn):
        return _cancel_restore()

    try:
        result = restore_workspace_backup(plan)
    except (
        CompatibilityManifestError,
        CoreWorkspaceQualificationError,
        CoreWorkspaceServiceError,
        WorkspaceBackupError,
        WorkspaceRestoreError,
        OSError,
    ) as error:
        message = str(error)[:500] or error.__class__.__name__
        print(f"Restore failed: {message}", file=sys.stderr)
        return 1

    print(render_workspace_restore_result(plan, result), end="")
    return 0


def _cancel_backup() -> int:
    print("Workspace backup cancelled. No backup was created.")
    return 0


def _print_refusal(error: Exception) -> None:
    message = str(error)[:500] or error.__class__.__name__
    print(f"Backup refused: {message}", file=sys.stderr)


def _print_failure(error: Exception) -> None:
    message = str(error)[:500] or error.__class__.__name__
    print(f"Backup failed: {message}", file=sys.stderr)


def _confirm_backup(input_fn: InputReader) -> bool:
    while True:
        choice = _read("Type BACKUP to create the backup, or Q to cancel: ", input_fn)
        if choice is None or choice == "Q":
            return False
        if choice == "BACKUP":
            return True
        print("Enter exact uppercase BACKUP to continue, or Q to cancel.")


def run_workspace_backup_create(
    destination: Path,
    *,
    assume_yes: bool = False,
    input_fn: InputReader = input,
) -> int:
    """Plan, confirm, create, verify, and publish one whole-workspace backup."""
    try:
        plan = plan_workspace_backup(destination)
    except (
        CompatibilityManifestError,
        CoreWorkspaceQualificationError,
        CoreWorkspaceServiceError,
        WorkspaceBackupError,
        OSError,
    ) as error:
        _print_refusal(error)
        return 1

    print(render_workspace_backup_plan(plan), end="")
    if not assume_yes and not _confirm_backup(input_fn):
        return _cancel_backup()

    try:
        result = create_workspace_backup(plan)
    except (
        CompatibilityManifestError,
        CoreWorkspaceQualificationError,
        CoreWorkspaceServiceError,
        WorkspaceBackupError,
        OSError,
    ) as error:
        _print_failure(error)
        return 1

    print(render_workspace_backup_result(plan, result), end="")
    return 0


__all__ = (
    "render_workspace_backup_plan",
    "render_workspace_backup_result",
    "render_workspace_backup_verification_result",
    "render_workspace_restore_plan",
    "render_workspace_restore_result",
    "run_workspace_backup_create",
    "run_workspace_backup_restore",
    "run_workspace_backup_verify",
)
