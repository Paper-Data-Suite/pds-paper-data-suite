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
from paper_data_suite.workspace_cli import workspace_source_label
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
    "run_workspace_backup_create",
)
