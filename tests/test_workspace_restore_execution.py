from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import paper_data_suite.workspace_restore as workspace_restore_module
from paper_data_suite.workspace_backup import (
    BACKUP_HASH_ALGORITHM,
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    WorkspaceBackupManifest,
    backup_name,
    serialize_workspace_backup_manifest,
)
from paper_data_suite.workspace_restore import (
    WorkspaceRestoreCollisionError,
    WorkspaceRestoreCopyError,
    WorkspaceRestoreDriftError,
    WorkspaceRestoreSpaceError,
    WorkspaceRestoreVerificationError,
    plan_workspace_restore,
    restore_workspace_backup,
)
from paper_data_suite.workspace_setup import CoreWorkspaceServices

FIXED = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)


def _backup(tmp_path: Path) -> Path:
    root = tmp_path / backup_name(FIXED)
    payload = root / "workspace"
    (payload / "empty").mkdir(parents=True)
    (payload / "nested").mkdir()
    (payload / "nested" / "alpha.bin").write_bytes(b"alpha")
    (payload / "zero").write_bytes(b"")
    files = (
        BackupFileEntry(
            path="nested/alpha.bin",
            size=5,
            sha256=hashlib.sha256(b"alpha").hexdigest(),
        ),
        BackupFileEntry(
            path="zero",
            size=0,
            sha256=hashlib.sha256(b"").hexdigest(),
        ),
    )
    manifest = WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=root.name,
        created_at=FIXED,
        suite_version="0.1.0",
        core_version="0.6.0",
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=2,
        file_count=2,
        total_bytes=5,
        directories=("empty", "nested"),
        files=files,
        exclusions=(),
    )
    root.mkdir(exist_ok=True)
    (root / "manifest.json").write_bytes(serialize_workspace_backup_manifest(manifest))
    return root


def _services(workspace: Path, source: str = "saved_config") -> CoreWorkspaceServices:
    def inspect(explicit_root=None):
        assert explicit_root is None
        return SimpleNamespace(root=workspace, source=source)

    def ensure_workspace_root(path, create=True):
        raise AssertionError("restore must not initialize a workspace")

    def save_workspace_root(path):
        raise AssertionError("restore must not save workspace selection")

    def clear_saved_workspace_root():
        raise AssertionError("restore must not clear workspace selection")

    return CoreWorkspaceServices(
        inspect_workspace_root=inspect,
        ensure_workspace_root=ensure_workspace_root,
        save_workspace_root=save_workspace_root,
        clear_saved_workspace_root=clear_saved_workspace_root,
    )


def _free(value: int):
    return lambda _path: SimpleNamespace(free=value)


def _plan(tmp_path: Path):
    backup = _backup(tmp_path)
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = tmp_path / "recovery" / "restored"
    plan = plan_workspace_restore(
        backup,
        destination,
        services=_services(workspace),
        disk_usage_reader=_free(10**9),
    )
    return backup, workspace, destination, plan


def test_restore_publishes_only_verified_payload(tmp_path: Path) -> None:
    backup, workspace, destination, plan = _plan(tmp_path)
    backup_before = {
        p.relative_to(backup).as_posix(): p.read_bytes()
        for p in backup.rglob("*")
        if p.is_file()
    }

    result = restore_workspace_backup(
        plan,
        services=_services(workspace),
        disk_usage_reader=_free(10**9),
        staging_nonce_factory=lambda: "fixed",
    )

    assert result.destination_root == destination.resolve()
    assert (destination / "nested" / "alpha.bin").read_bytes() == b"alpha"
    assert (destination / "zero").read_bytes() == b""
    assert (destination / "empty").is_dir()
    assert not (destination / "manifest.json").exists()
    assert workspace.exists()
    assert backup_before == {
        p.relative_to(backup).as_posix(): p.read_bytes()
        for p in backup.rglob("*")
        if p.is_file()
    }


def test_restore_reverifies_backup_before_destination_mutation(tmp_path: Path) -> None:
    backup, workspace, destination, plan = _plan(tmp_path)
    (backup / "workspace" / "nested" / "alpha.bin").write_bytes(b"omega")

    with pytest.raises(WorkspaceRestoreDriftError, match="no longer verifies"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
        )

    assert not destination.parent.exists()


def test_restore_rechecks_core_resolution_before_mutation(tmp_path: Path) -> None:
    _backup, _workspace, destination, plan = _plan(tmp_path)
    changed = tmp_path / "other-active"

    with pytest.raises(WorkspaceRestoreDriftError, match="resolved workspace changed"):
        restore_workspace_backup(
            plan,
            services=_services(changed),
            disk_usage_reader=_free(10**9),
        )

    assert not destination.parent.exists()


def test_restore_rechecks_free_space_before_staging(tmp_path: Path) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)
    destination.parent.mkdir(parents=True)

    with pytest.raises(WorkspaceRestoreSpaceError, match="Insufficient"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(plan.required_free_bytes - 1),
        )

    assert not destination.exists()
    assert tuple(destination.parent.iterdir()) == ()


def test_restore_rechecks_free_space_before_creating_missing_parent(
    tmp_path: Path,
) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)
    assert not destination.parent.exists()

    with pytest.raises(WorkspaceRestoreSpaceError, match="Insufficient"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(plan.required_free_bytes - 1),
        )

    assert not destination.parent.exists()
    assert not destination.exists()


def test_restore_preserves_preexisting_staging_collision(tmp_path: Path) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)
    destination.parent.mkdir(parents=True)
    staging = destination.parent / ".restored.pds-restore.incomplete-fixed"
    staging.mkdir()
    sentinel = staging / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(WorkspaceRestoreCollisionError, match="staging path"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not destination.exists()


def test_restore_detects_backup_drift_after_copy_and_cleans(tmp_path: Path) -> None:
    backup, workspace, destination, plan = _plan(tmp_path)

    def mutate(payload: Path, _staging: Path) -> None:
        (payload / "nested" / "alpha.bin").write_bytes(b"omega")

    with pytest.raises(WorkspaceRestoreDriftError, match="changed while"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=mutate,
        )

    assert not destination.exists()
    assert not (
        destination.parent / ".restored.pds-restore.incomplete-fixed"
    ).exists()
    assert (backup / "workspace" / "nested" / "alpha.bin").read_bytes() == b"omega"


def test_restore_detects_staged_corruption_and_cleans(tmp_path: Path) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)

    def corrupt(_payload: Path, staging: Path) -> None:
        (staging / "nested" / "alpha.bin").write_bytes(b"omega")

    with pytest.raises(WorkspaceRestoreVerificationError, match="SHA-256"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=corrupt,
        )

    assert not destination.exists()
    assert not (
        destination.parent / ".restored.pds-restore.incomplete-fixed"
    ).exists()


def test_restore_copy_failure_cleans_owned_staging(tmp_path: Path) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)

    def fail(_payload: Path, _staging: Path, expected: BackupFileEntry, _size: int):
        raise WorkspaceRestoreCopyError(f"synthetic failure: {expected.path}")

    with pytest.raises(WorkspaceRestoreCopyError, match="synthetic"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
            file_copier=fail,
        )

    assert not destination.exists()
    assert not (
        destination.parent / ".restored.pds-restore.incomplete-fixed"
    ).exists()


def test_restore_publication_collision_preserves_existing_destination(
    tmp_path: Path,
) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)

    def collide(_staging: Path, final: Path) -> None:
        final.mkdir()
        (final / "sentinel").write_text("keep", encoding="utf-8")

    with pytest.raises(WorkspaceRestoreCollisionError, match="already exists"):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
            before_publish_hook=collide,
        )

    assert (destination / "sentinel").read_text(encoding="utf-8") == "keep"
    assert not (
        destination.parent / ".restored.pds-restore.incomplete-fixed"
    ).exists()

def test_publication_race_does_not_replace_existing_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / ".restore.incomplete-fixed"
    final = tmp_path / "restored"
    staging.mkdir()
    sentinel = staging / "sentinel"
    sentinel.write_text("staged", encoding="utf-8")
    final.mkdir()

    monkeypatch.setattr(
        workspace_restore_module,
        "_path_entry_exists",
        lambda _path: False,
    )

    with pytest.raises(WorkspaceRestoreCollisionError, match="already exists"):
        workspace_restore_module._publish_staging(staging, final)

    assert final.is_dir()
    assert tuple(final.iterdir()) == ()
    assert sentinel.read_text(encoding="utf-8") == "staged"


def test_restore_cleanup_failure_reports_remaining_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _backup, workspace, destination, plan = _plan(tmp_path)
    remaining = (
        destination.parent
        / ".restored.pds-restore.incomplete-fixed"
    )

    def fail_copy(
        _payload: Path,
        _staging: Path,
        expected: BackupFileEntry,
        _size: int,
    ) -> BackupFileEntry:
        raise WorkspaceRestoreCopyError(f"synthetic failure: {expected.path}")

    monkeypatch.setattr(
        "paper_data_suite.workspace_restore._cleanup_staging",
        lambda _path: str(remaining),
    )

    with pytest.raises(
        WorkspaceRestoreCopyError,
        match="Incomplete restore staging remains",
    ):
        restore_workspace_backup(
            plan,
            services=_services(workspace),
            disk_usage_reader=_free(10**9),
            staging_nonce_factory=lambda: "fixed",
            file_copier=fail_copy,
        )

