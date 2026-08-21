from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.cli import build_parser, main
from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    WorkspaceBackupManifest,
    backup_name,
    serialize_workspace_backup_manifest,
)
from paper_data_suite.workspace_backup_cli import run_workspace_backup_verify

FIXED_TIME = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)


def _empty_backup(tmp_path: Path) -> Path:
    root = tmp_path / backup_name(FIXED_TIME)
    (root / "workspace").mkdir(parents=True)
    manifest = WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=root.name,
        created_at=FIXED_TIME,
        suite_version="0.1.0.dev0",
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
    (root / "manifest.json").write_bytes(serialize_workspace_backup_manifest(manifest))
    return root


def test_parser_accepts_backup_verify() -> None:
    arguments = build_parser().parse_args(["backup", "verify", "example"])
    assert arguments.command == "backup"
    assert arguments.backup_command == "verify"
    assert arguments.backup == Path("example")


def test_verify_cli_renders_bounded_success(
    tmp_path: Path, capsys  # type: ignore[no-untyped-def]
) -> None:
    backup = _empty_backup(tmp_path)

    assert run_workspace_backup_verify(backup) == 0

    output = capsys.readouterr()
    assert "Workspace backup verified" in output.out
    assert f"Backup: {backup.resolve()}" in output.out
    assert "Backup ID:" in output.out
    assert "Recorded suite version: 0.1.0.dev0" in output.out
    assert "Recorded Core version: 0.6.0" in output.out
    assert "Directories: 0" in output.out
    assert "Files: 0" in output.out
    assert "Payload bytes: 0" in output.out
    assert "Manifest SHA-256:" in output.out
    assert "authentic" not in output.out.lower()
    assert output.err == ""


def test_verify_cli_failure_is_bounded(
    tmp_path: Path, capsys  # type: ignore[no-untyped-def]
) -> None:
    missing = tmp_path / "missing"

    assert run_workspace_backup_verify(missing) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("Backup verification failed:")
    assert len(output.err) < 700


def test_main_dispatches_backup_verify(
    tmp_path: Path, capsys  # type: ignore[no-untyped-def]
) -> None:
    backup = _empty_backup(tmp_path)

    assert main(["backup", "verify", str(backup)]) == 0
    assert "Workspace backup verified" in capsys.readouterr().out
