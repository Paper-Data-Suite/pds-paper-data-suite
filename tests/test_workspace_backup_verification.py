from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    WorkspaceBackupManifest,
    WorkspaceBackupVerificationError,
    backup_name,
    serialize_workspace_backup_manifest,
)
from paper_data_suite.workspace_backup_verification import verify_workspace_backup

FIXED_TIME = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)


def _write_backup(tmp_path: Path) -> tuple[Path, WorkspaceBackupManifest]:
    backup_root = tmp_path / backup_name(FIXED_TIME)
    payload = backup_root / BACKUP_PAYLOAD_ROOT
    (payload / "classes" / "future-module" / "empty").mkdir(parents=True)
    (payload / ".pds").mkdir()
    (payload / "classes" / "future-module" / "opaque.bin").write_bytes(b"\x00\xffx")
    (payload / "zero.dat").write_bytes(b"")
    (payload / "unicodé.txt").write_text("hello", encoding="utf-8")
    files = tuple(
        BackupFileEntry(
            path=path,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for path, data in (
            ("classes/future-module/opaque.bin", b"\x00\xffx"),
            ("unicodé.txt", b"hello"),
            ("zero.dat", b""),
        )
    )
    manifest = WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=backup_root.name,
        created_at=FIXED_TIME,
        suite_version="0.1.0.dev0",
        core_version="0.6.0",
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=4,
        file_count=3,
        total_bytes=8,
        directories=(
            ".pds",
            "classes",
            "classes/future-module",
            "classes/future-module/empty",
        ),
        files=files,
        exclusions=(),
    )
    (backup_root / "manifest.json").write_bytes(
        serialize_workspace_backup_manifest(manifest)
    )
    return backup_root, manifest


def test_verify_accepts_complete_backup_without_core_or_module_semantics(
    tmp_path: Path,
) -> None:
    backup_root, manifest = _write_backup(tmp_path)

    result = verify_workspace_backup(backup_root, chunk_size=2)

    assert result.backup_root == backup_root.resolve()
    assert result.manifest == manifest
    assert result.payload_root == backup_root.resolve() / "workspace"
    assert result.manifest_sha256 == hashlib.sha256(
        (backup_root / "manifest.json").read_bytes()
    ).hexdigest()


def test_verify_allows_backup_moved_to_different_parent(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path / "original")
    moved_parent = tmp_path / "moved"
    moved_parent.mkdir()
    moved = moved_parent / backup_root.name
    backup_root.rename(moved)

    assert verify_workspace_backup(moved).backup_root == moved.resolve()


def test_verify_rejects_renamed_backup_root(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    renamed = backup_root.with_name("pds-workspace-backup-20260820T174812999999Z")
    backup_root.rename(renamed)

    with pytest.raises(WorkspaceBackupVerificationError, match="backup_id"):
        verify_workspace_backup(renamed)


def test_verify_rejects_incomplete_staging_name(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    incomplete = backup_root.with_name(f".{backup_root.name}.incomplete-deadbeef")
    backup_root.rename(incomplete)

    with pytest.raises(WorkspaceBackupVerificationError, match="Incomplete"):
        verify_workspace_backup(incomplete)


def test_verify_rejects_missing_or_extra_top_level_state(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path / "missing")
    (backup_root / "manifest.json").unlink()
    with pytest.raises(WorkspaceBackupVerificationError, match="missing manifest"):
        verify_workspace_backup(backup_root)

    backup_root, _manifest = _write_backup(tmp_path / "extra")
    (backup_root / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceBackupVerificationError, match="unexpected"):
        verify_workspace_backup(backup_root)


def test_verify_rejects_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    manifest_path = backup_root / "manifest.json"
    mapping = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(mapping), encoding="utf-8")

    with pytest.raises(WorkspaceBackupVerificationError, match="canonical"):
        verify_workspace_backup(backup_root)


def test_verify_detects_same_size_payload_corruption(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    payload = backup_root / "workspace" / "unicodé.txt"
    payload.write_bytes(b"HELLO")

    with pytest.raises(WorkspaceBackupVerificationError, match="SHA-256"):
        verify_workspace_backup(backup_root)


@pytest.mark.parametrize("mutation", ("extra-file", "missing-file", "missing-dir"))
def test_verify_requires_exact_payload_inventory(tmp_path: Path, mutation: str) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    payload = backup_root / "workspace"
    if mutation == "extra-file":
        (payload / ".unexpected").write_bytes(b"x")
    elif mutation == "missing-file":
        (payload / "zero.dat").unlink()
    else:
        (payload / "classes" / "future-module" / "empty").rmdir()

    with pytest.raises(WorkspaceBackupVerificationError, match="inventory"):
        verify_workspace_backup(backup_root)


def test_verify_rejects_linked_payload_entry_without_following(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    payload = backup_root / "workspace"
    target = tmp_path / "outside.txt"
    target.write_bytes(b"do-not-read")
    linked = payload / "zero.dat"
    linked.unlink()
    try:
        linked.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(WorkspaceBackupVerificationError, match="linked"):
        verify_workspace_backup(backup_root)


def test_verify_rejects_backup_root_file(tmp_path: Path) -> None:
    root = tmp_path / "pds-workspace-backup-20260820T174812123456Z"
    root.write_bytes(b"not-a-directory")

    with pytest.raises(WorkspaceBackupVerificationError, match="not a directory"):
        verify_workspace_backup(root)


def test_verify_rejects_backup_root_symlink_without_following(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path / "target")
    linked = tmp_path / "backup-link"
    try:
        linked.symlink_to(backup_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")

    with pytest.raises(
        WorkspaceBackupVerificationError,
        match="redirecting filesystem entry",
    ):
        verify_workspace_backup(linked)


def test_verify_rejects_invalid_chunk_size(tmp_path: Path) -> None:
    backup_root, _manifest = _write_backup(tmp_path)
    with pytest.raises(ValueError, match="greater than zero"):
        verify_workspace_backup(backup_root, chunk_size=0)
