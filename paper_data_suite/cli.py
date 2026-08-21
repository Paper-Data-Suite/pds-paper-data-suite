"""Command-line interface for the Paper Data Suite shell."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from paper_data_suite._version import __version__
from paper_data_suite.application_launching import (
    ApplicationLaunchExecutionError,
    ApplicationLaunchRefusedError,
    launch_application,
    resolve_application_launchers,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    collect_application_inventory,
)
from paper_data_suite.classroom_setup_cli import run_classroom_setup
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    ComponentCompatibility,
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
)
from paper_data_suite.doctor import collect_doctor_diagnostics, render_doctor_report
from paper_data_suite.settings import SuiteSettingsError, record_recent_component
from paper_data_suite.settings_cli import (
    run_settings_clear_recent,
    run_settings_reset,
    run_settings_show,
)
from paper_data_suite.workspace_backup_cli import (
    run_workspace_backup_create,
    run_workspace_backup_restore,
    run_workspace_backup_verify,
)
from paper_data_suite.workspace_cli import (
    run_workspace_reset,
    run_workspace_set,
    run_workspace_setup,
    run_workspace_show,
    run_workspace_validate,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the Paper Data Suite command-line parser."""
    parser = argparse.ArgumentParser(
        prog="pds",
        description=(
            "Paper Data Suite suite shell. Operational commands provide bounded, "
            "teacher-facing suite workflows."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    doctor = subparsers.add_parser(
        "doctor",
        help="diagnose the installed suite environment without modifying it",
        description=(
            "Diagnose Paper Data Suite runtime, packages, dependencies, public "
            "integration contracts, workspace access, and Core registry health."
        ),
    )
    doctor.add_argument(
        "--workspace",
        type=Path,
        help=(
            "inspect this workspace for this invocation only; do not save or "
            "initialize it"
        ),
    )
    workspace = subparsers.add_parser(
        "workspace",
        help="inspect, validate, select, or reset the shared Core workspace",
        description=(
            "Inspect or explicitly change the shared Paper Data Suite workspace "
            "through suite-qualified public Core services."
        ),
    )
    workspace.set_defaults(workspace_parser=workspace)
    workspace_subparsers = workspace.add_subparsers(dest="workspace_command")
    workspace_subparsers.add_parser(
        "setup",
        help="run guided review-before-write workspace setup",
        description=(
            "Guided workspace selection through Core with candidate preview, "
            "explicit confirmation, and safe cancellation."
        ),
    )
    workspace_subparsers.add_parser(
        "show",
        help="show the currently resolved workspace without changing it",
    )
    workspace_validate = workspace_subparsers.add_parser(
        "validate",
        help="validate an existing workspace without creating or saving it",
    )
    workspace_validate.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="optional explicit workspace candidate; default is current resolution",
    )
    workspace_set = workspace_subparsers.add_parser(
        "set",
        help="initialize and save an explicit workspace through Core",
    )
    workspace_set.add_argument(
        "path",
        type=Path,
        help="workspace path to initialize and save",
    )
    workspace_subparsers.add_parser(
        "reset",
        help="clear only Core's saved workspace preference",
    )
    settings = subparsers.add_parser(
        "settings",
        help="inspect, clear, or reset suite-owned shell convenience settings",
        description=(
            "Inspect or manage privacy-minimized per-user Paper Data Suite shell "
            "settings. These settings never own Core workspace selection or "
            "module workflow state."
        ),
    )
    settings.set_defaults(settings_parser=settings)
    settings_subparsers = settings.add_subparsers(dest="settings_command")
    settings_subparsers.add_parser(
        "show",
        help="show bounded suite settings and current component availability",
        description=(
            "Show suite-owned convenience settings without dumping raw JSON or "
            "treating settings as a workspace authority."
        ),
    )
    settings_subparsers.add_parser(
        "clear-recent",
        help="clear only recent top-level suite component context",
        description=(
            "Clear only the bounded recent-component list. Core workspace "
            "selection and module-owned context are not changed."
        ),
    )
    settings_subparsers.add_parser(
        "reset",
        help="replace only suite shell settings with safe defaults",
        description=(
            "Atomically replace the suite preference document with schema-v1 "
            "defaults without changing Core workspace selection or module state."
        ),
    )
    backup = subparsers.add_parser(
        "backup",
        help="create, verify, or safely restore whole-workspace backups",
        description=(
            "Create protected whole-workspace backups, independently verify a "
            "completed backup, or restore verified opaque workspace bytes to a "
            "new explicit alternate location. Restore never automatically selects "
            "the recovered workspace."
        ),
    )
    backup.set_defaults(backup_parser=backup)
    backup_subparsers = backup.add_subparsers(dest="backup_command")
    backup_create = backup_subparsers.add_parser(
        "create",
        help="create one timestamped non-overwriting workspace backup",
        description=(
            "Create a timestamped, non-overwriting backup of the currently resolved "
            "Core workspace. --destination is the explicit parent directory for the "
            "new backup. The backup contains the same potentially sensitive data as "
            "the workspace. PDS does not encrypt, upload, or cloud-sync the backup."
        ),
    )
    backup_create.add_argument(
        "--destination",
        required=True,
        type=Path,
        help="explicit parent directory under which the timestamped backup is created",
    )
    backup_create.add_argument(
        "--yes",
        action="store_true",
        help="create after preflight without the interactive BACKUP confirmation",
    )
    backup_verify = backup_subparsers.add_parser(
        "verify",
        help="independently verify a completed workspace backup",
        description=(
            "Verify the completed backup-v1 manifest, exact payload inventory, "
            "sizes, and SHA-256 hashes without modifying the backup or resolving "
            "the active Core workspace. Integrity verification is not a digital "
            "signature or runtime-compatibility guarantee."
        ),
    )
    backup_verify.add_argument(
        "backup",
        type=Path,
        help="explicit completed backup root containing manifest.json and workspace/",
    )
    backup_restore = backup_subparsers.add_parser(
        "restore",
        help="restore a verified backup to a new alternate workspace location",
        description=(
            "Verify a completed backup and restore its opaque workspace payload to "
            "one explicit destination that must not already exist. The active Core "
            "workspace is protected and the restored workspace is not selected "
            "automatically."
        ),
    )
    backup_restore.add_argument(
        "backup",
        type=Path,
        help="explicit completed backup root containing manifest.json and workspace/",
    )
    backup_restore.add_argument(
        "--destination",
        required=True,
        type=Path,
        help="exact final restored workspace root; it must not already exist",
    )
    backup_restore.add_argument(
        "--yes",
        action="store_true",
        help="restore after full preflight without interactive RESTORE confirmation",
    )
    subparsers.add_parser(
        "setup",
        help="run guided shared school-year and classroom setup",
        description=(
            "Guided shared setup over the currently resolved Core workspace. "
            "Review school year, classes, rosters, standards, and an initial "
            "Academic Period calendar before any persistent change; only exact "
            "APPLY authorizes Core writes."
        ),
    )
    subparsers.add_parser(
        "modules",
        help="list applications this suite release supports launching",
        description=(
            "List suite-qualified teacher applications and their current launch "
            "availability without importing or starting them."
        ),
    )
    launch = subparsers.add_parser(
        "launch",
        help="launch one suite-qualified application menu",
        description=(
            "Launch one suite-qualified application through its verified public "
            "console boundary."
        ),
    )
    launch.add_argument(
        "component_id",
        help="stable suite component ID, for example scoreform or quillan",
    )
    return parser


def _status_label(status: ApplicationLaunchStatus) -> str:
    return {
        ApplicationLaunchStatus.AVAILABLE: "available",
        ApplicationLaunchStatus.NOT_INSTALLED: "not installed",
        ApplicationLaunchStatus.INCOMPATIBLE: "incompatible",
        ApplicationLaunchStatus.UNAVAILABLE: "unavailable",
    }[status]


def render_application_inventory(inventory: ApplicationInventory) -> str:
    """Render a concise deterministic teacher-facing application inventory."""
    lines = ["Paper Data Suite applications", ""]
    for application in inventory.applications:
        lines.extend(
            (
                application.display_name,
                f"  Purpose: {application.purpose}",
                f"  Status: {_status_label(application.status)}",
                f"  Component ID: {application.component_id}",
                f"  Suite-qualified version: {application.qualified_version}",
                "  Installed version: "
                + (application.installed_version or "not installed"),
            )
        )
        if (
            application.status is ApplicationLaunchStatus.AVAILABLE
            and application.launcher_path is not None
        ):
            lines.append(f"  Launch: pds launch {application.component_id}")
        else:
            lines.append(f"  Reason: {application.reason}")
            if application.remediation is not None:
                lines.append(f"  Remediation: {application.remediation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolved_inventory(
    manifest: ReleaseCompatibilityManifest,
) -> ApplicationInventory:
    inventory = collect_application_inventory(manifest)
    return resolve_application_launchers(inventory)


def _print_inventory_failure(error: Exception) -> None:
    message = str(error)[:500] or error.__class__.__name__
    print(f"Application inventory failed: {message}", file=sys.stderr)


def _run_modules() -> int:
    try:
        manifest = load_release_compatibility_manifest()
        inventory = _resolved_inventory(manifest)
    except (ApplicationInventoryError, CompatibilityManifestError, OSError) as error:
        _print_inventory_failure(error)
        return 1

    print(render_application_inventory(inventory), end="")
    return 0


def _manifest_component(
    manifest: ReleaseCompatibilityManifest,
    component_id: str,
) -> ComponentCompatibility | None:
    return next(
        (
            component
            for component in manifest.components
            if component.component_id == component_id
        ),
        None,
    )


def _run_launch(component_id: str) -> int:
    try:
        manifest = load_release_compatibility_manifest()
    except (CompatibilityManifestError, OSError) as error:
        _print_inventory_failure(error)
        return 1

    component = _manifest_component(manifest, component_id)
    if component is None:
        print(
            f"Unknown Paper Data Suite component ID: {component_id}.",
            file=sys.stderr,
        )
        return 2
    if "launchable_application" not in component.capabilities:
        print(
            f"{component.display_name} is known to this suite release but is not a "
            "suite-launchable application.",
            file=sys.stderr,
        )
        return 1

    try:
        inventory = _resolved_inventory(manifest)
    except (ApplicationInventoryError, CompatibilityManifestError, OSError) as error:
        _print_inventory_failure(error)
        return 1

    application = inventory.for_component(component_id)
    if application is None:
        print(
            f"Application inventory does not contain component {component_id}.",
            file=sys.stderr,
        )
        return 1

    if (
        application.status is not ApplicationLaunchStatus.AVAILABLE
        or application.launcher_path is None
    ):
        print(
            f"Cannot launch {application.display_name}: {application.reason}",
            file=sys.stderr,
        )
        if application.remediation is not None:
            print(f"Remediation: {application.remediation}", file=sys.stderr)
        return 1

    try:
        result = launch_application(application)
    except (ApplicationLaunchExecutionError, ApplicationLaunchRefusedError) as error:
        print(f"Launch failed: {error}", file=sys.stderr)
        return 1

    try:
        record_recent_component(result.component_id)
    except SuiteSettingsError as error:
        message = str(error)[:300] or error.__class__.__name__
        print(
            "Warning: application started, but recent component context was not saved.",
            file=sys.stderr,
        )
        print(f"Settings detail: {message}", file=sys.stderr)

    if not result.succeeded:
        print(
            f"{result.display_name} exited with status {result.exit_code}.",
            file=sys.stderr,
        )
        print(
            f"The {result.display_name} application reported a non-success status.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Paper Data Suite command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "doctor":
        report = collect_doctor_diagnostics(workspace=arguments.workspace)
        print(render_doctor_report(report), end="")
        return report.exit_code
    if arguments.command == "workspace":
        if arguments.workspace_command is None:
            arguments.workspace_parser.print_help()
            return 0
        if arguments.workspace_command == "setup":
            return run_workspace_setup()
        if arguments.workspace_command == "show":
            return run_workspace_show()
        if arguments.workspace_command == "validate":
            return run_workspace_validate(arguments.path)
        if arguments.workspace_command == "set":
            return run_workspace_set(arguments.path)
        if arguments.workspace_command == "reset":
            return run_workspace_reset()
        raise AssertionError(
            f"unhandled workspace command: {arguments.workspace_command}"
        )
    if arguments.command == "settings":
        if arguments.settings_command is None:
            arguments.settings_parser.print_help()
            return 0
        if arguments.settings_command == "show":
            return run_settings_show()
        if arguments.settings_command == "clear-recent":
            return run_settings_clear_recent()
        if arguments.settings_command == "reset":
            return run_settings_reset()
        raise AssertionError(
            f"unhandled settings command: {arguments.settings_command}"
        )
    if arguments.command == "backup":
        if arguments.backup_command is None:
            arguments.backup_parser.print_help()
            return 0
        if arguments.backup_command == "create":
            return run_workspace_backup_create(
                arguments.destination,
                assume_yes=arguments.yes,
            )
        if arguments.backup_command == "verify":
            return run_workspace_backup_verify(arguments.backup)
        if arguments.backup_command == "restore":
            return run_workspace_backup_restore(
                arguments.backup,
                arguments.destination,
                assume_yes=arguments.yes,
            )
        raise AssertionError(f"unhandled backup command: {arguments.backup_command}")
    if arguments.command == "setup":
        return run_classroom_setup()
    if arguments.command == "modules":
        return _run_modules()
    if arguments.command == "launch":
        return _run_launch(arguments.component_id)
    parser.print_help()
    return 0
