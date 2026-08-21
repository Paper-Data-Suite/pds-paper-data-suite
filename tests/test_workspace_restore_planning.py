from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

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
    required_backup_free_bytes,
    serialize_workspace_backup_manifest,
)
from paper_data_suite.workspace_backup_verification import (
    WorkspaceBackupVerificationResult,
    verify_workspace_backup,
)
from paper_data_suite.workspace_restore import (
    WorkspaceRestoreDestinationError,
    WorkspaceRestoreSpaceError,
    plan_workspace_restore,
)
from paper_data_suite.workspace_setup import (
    CoreWorkspaceServices,
    WorkspaceEnsurer,
    WorkspaceInspector,
    WorkspaceResetter,
    WorkspaceSaver,
)

FIXED_TIME = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)
BACKUP_ID = backup_name(FIXED_TIME)


@dataclass
class FakeStatus:
    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool
    config_path: Path
    default_root: Path


class FakeCore:
    def __init__(self, root: Path, *, exists: bool = True) -> None:
        self.root = root
        self.exists = exists
        self.inspect_calls = 0
        self.mutation_calls = 0

    def inspect(self, explicit_root: str | Path | None = None) -> FakeStatus:
        assert explicit_root is None
        self.inspect_calls += 1
        return FakeStatus(
            root=self.root,
            source="saved_config",
            exists=self.exists,
            is_dir=self.root.is_dir() if self.exists else False,
            is_writable=False,
            config_path=self.root.parent / "config.json",
            default_root=self.root.parent / "default",
        )

    def mutate(self, *_args: object, **_kwargs: object) -> object:
        self.mutation_calls += 1
        raise AssertionError("restore planning must not call Core mutation services")

    def services(self) -> CoreWorkspaceServices:
        return CoreWorkspaceServices(
            inspect_workspace_root=cast(WorkspaceInspector, self.inspect),
            ensure_workspace_root=cast(WorkspaceEnsurer, self.mutate),
            save_workspace_root=cast(WorkspaceSaver, self.mutate),
            clear_saved_workspace_root=cast(WorkspaceResetter, self.mutate),
        )


def free_space(value: int):  # type: ignore[no-untyped-def]
    return lambda _path: SimpleNamespace(total=value * 2, used=value, free=value)


def make_backup(tmp_path: Path) -> Path:
    root = tmp_path / BACKUP_ID
    payload = root / "workspace"
    (payload / "empty").mkdir(parents=True)
    (payload / "alpha.bin").write_bytes(b"alpha")
    digest = hashlib.sha256(b"alpha").hexdigest()
    manifest = WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=BACKUP_ID,
        created_at=FIXED_TIME,
        suite_version="0.1.0",
        core_version="0.6.0",
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=1,
        file_count=1,
        total_bytes=5,
        directories=("empty",),
        files=(BackupFileEntry(path="alpha.bin", size=5, sha256=digest),),
        exclusions=(),
    )
    (root / "manifest.json").write_bytes(serialize_workspace_backup_manifest(manifest))
    return root


def test_restore_plan_fully_verifies_before_core_and_is_read_only(
    tmp_path: Path,
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = tmp_path / "recovery" / "restored"
    core = FakeCore(workspace)
    required = required_backup_free_bytes(5)
    events: list[str] = []

    def verifier(path: str | Path) -> WorkspaceBackupVerificationResult:
        events.append("verify")
        return verify_workspace_backup(path)

    def loader() -> CoreWorkspaceServices:
        events.append("core")
        return core.services()

    plan = plan_workspace_restore(
        backup,
        destination,
        services_loader=loader,
        verifier=verifier,
        disk_usage_reader=free_space(required),
    )

    assert events == ["verify", "core"]
    assert core.inspect_calls == 1
    assert core.mutation_calls == 0
    assert plan.backup_root == backup.resolve()
    assert plan.workspace_root == workspace.resolve()
    assert plan.workspace_source == "saved_config"
    assert plan.destination_root == destination.resolve()
    assert plan.destination_parent == destination.parent.resolve()
    assert plan.destination_anchor == tmp_path.resolve()
    assert plan.destination_parent_exists is False
    assert plan.destination_free_bytes == required
    assert plan.required_free_bytes == required
    assert not destination.exists()
    assert (backup / "workspace" / "alpha.bin").read_bytes() == b"alpha"


def test_restore_plan_uses_provided_services_without_loader(tmp_path: Path) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    core = FakeCore(workspace)

    def forbidden_loader() -> CoreWorkspaceServices:
        raise AssertionError("provided services should be used")

    plan = plan_workspace_restore(
        backup,
        tmp_path / "restored",
        services=core.services(),
        services_loader=forbidden_loader,
        disk_usage_reader=free_space(10**9),
    )

    assert plan.workspace_root == workspace.resolve()
    assert core.mutation_calls == 0


@pytest.mark.parametrize("kind", ("empty-dir", "full-dir", "file"))
def test_restore_plan_refuses_any_existing_destination(
    tmp_path: Path,
    kind: str,
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = tmp_path / "restored"
    if kind == "empty-dir":
        destination.mkdir()
    elif kind == "full-dir":
        destination.mkdir()
        (destination / "sentinel").write_text("keep", encoding="utf-8")
    else:
        destination.write_text("keep", encoding="utf-8")

    with pytest.raises(WorkspaceRestoreDestinationError, match="already exists"):
        plan_workspace_restore(
            backup,
            destination,
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(10**9),
        )


@pytest.mark.parametrize(
    "destination_factory",
    (
        lambda backup, _workspace: backup / "new-workspace",
        lambda backup, _workspace: backup / "workspace" / "nested",
        lambda backup, _workspace: _workspace / "alternate",
    ),
)
def test_restore_plan_refuses_destination_inside_protected_tree(
    tmp_path: Path,
    destination_factory,  # type: ignore[no-untyped-def]
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = destination_factory(backup, workspace)

    with pytest.raises(WorkspaceRestoreDestinationError, match="overlap"):
        plan_workspace_restore(
            backup,
            destination,
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(10**9),
        )


def test_restore_plan_refuses_resolved_workspace_even_when_missing(
    tmp_path: Path,
) -> None:
    backup = make_backup(tmp_path / "backups")
    missing_workspace = tmp_path / "missing-active"

    with pytest.raises(WorkspaceRestoreDestinationError, match="resolved workspace"):
        plan_workspace_restore(
            backup,
            missing_workspace,
            services=FakeCore(missing_workspace, exists=False).services(),
            disk_usage_reader=free_space(10**9),
        )


def test_restore_plan_refuses_destination_containing_missing_workspace(
    tmp_path: Path,
) -> None:
    backup = make_backup(tmp_path / "backups")
    destination = tmp_path / "recovery"
    missing_workspace = destination / "future-active"

    with pytest.raises(WorkspaceRestoreDestinationError, match="resolved workspace"):
        plan_workspace_restore(
            backup,
            destination,
            services=FakeCore(missing_workspace, exists=False).services(),
            disk_usage_reader=free_space(10**9),
        )


def test_restore_plan_resolves_destination_alias_before_containment(
    tmp_path: Path,
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    alias = tmp_path / "active-alias"
    try:
        alias.symlink_to(workspace, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")

    with pytest.raises(WorkspaceRestoreDestinationError, match="resolved workspace"):
        plan_workspace_restore(
            backup,
            alias / "restored",
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(10**9),
        )


def test_restore_plan_refuses_below_free_space_threshold_and_accepts_exact(
    tmp_path: Path,
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    required = required_backup_free_bytes(5)

    with pytest.raises(WorkspaceRestoreSpaceError, match="Insufficient"):
        plan_workspace_restore(
            backup,
            tmp_path / "restore-low",
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(required - 1),
        )

    plan = plan_workspace_restore(
        backup,
        tmp_path / "restore-exact",
        services=FakeCore(workspace).services(),
        disk_usage_reader=free_space(required),
    )
    assert plan.required_free_bytes == required
    assert plan.destination_free_bytes == required


def test_restore_plan_reports_free_space_provider_failure(tmp_path: Path) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()

    def fail(_path: str | Path):  # type: ignore[no-untyped-def]
        raise OSError("synthetic free-space failure")

    with pytest.raises(WorkspaceRestoreDestinationError, match="free space"):
        plan_workspace_restore(
            backup,
            tmp_path / "restored",
            services=FakeCore(workspace).services(),
            disk_usage_reader=fail,
        )


def test_restore_plan_verification_failure_happens_before_core(tmp_path: Path) -> None:
    bad_backup = tmp_path / "missing-backup"
    core_loaded = False

    def loader() -> CoreWorkspaceServices:
        nonlocal core_loaded
        core_loaded = True
        raise AssertionError("Core must not load before backup verification")

    with pytest.raises(WorkspaceBackupVerificationError, match="Backup"):
        plan_workspace_restore(
            bad_backup,
            tmp_path / "restored",
            services_loader=loader,
            disk_usage_reader=free_space(10**9),
        )

    assert core_loaded is False

def test_restore_plan_refuses_existing_destination_after_environment_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = tmp_path / "existing-restore"
    destination.mkdir()
    monkeypatch.setenv("PDS_RESTORE_TEST_ROOT", str(tmp_path))

    with pytest.raises(WorkspaceRestoreDestinationError, match="already exists"):
        plan_workspace_restore(
            backup,
            Path("$PDS_RESTORE_TEST_ROOT") / "existing-restore",
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(10**9),
        )


def test_restore_plan_refuses_dangling_destination_symlink(tmp_path: Path) -> None:
    backup = make_backup(tmp_path / "backups")
    workspace = tmp_path / "active"
    workspace.mkdir()
    destination = tmp_path / "dangling-restore"
    target = tmp_path / "not-created-target"
    try:
        destination.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")

    with pytest.raises(WorkspaceRestoreDestinationError, match="already exists"):
        plan_workspace_restore(
            backup,
            destination,
            services=FakeCore(workspace).services(),
            disk_usage_reader=free_space(10**9),
        )

