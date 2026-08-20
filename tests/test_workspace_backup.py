from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from paper_data_suite.compatibility import load_release_compatibility_manifest
from paper_data_suite.workspace_backup import (
    BACKUP_MANIFEST_RECORD_TYPE,
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BACKUP_MINIMUM_RESERVE_BYTES,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    CoreBackupServices,
    WorkspaceBackupCollisionError,
    WorkspaceBackupCopyError,
    WorkspaceBackupDestinationError,
    WorkspaceBackupDriftError,
    WorkspaceBackupManifestError,
    WorkspaceBackupSourceError,
    WorkspaceBackupSpaceError,
    WorkspaceBackupUnsupportedEntryError,
    WorkspaceBackupVerificationError,
    backup_name,
    create_workspace_backup,
    create_workspace_backup_manifest,
    inventory_workspace,
    load_core_backup_services,
    parse_workspace_backup_manifest,
    plan_workspace_backup,
    required_backup_free_bytes,
    serialize_workspace_backup_manifest,
    workspace_backup_manifest_sha256,
)
from paper_data_suite.workspace_setup import WorkspaceInspector


@dataclass
class FakeStatus:
    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool
    config_path: Path
    default_root: Path


class FakeCoreBackup:
    def __init__(
        self,
        root: Path,
        *,
        source: str = "saved_config",
        exists: bool | None = None,
        is_dir: bool | None = None,
    ) -> None:
        self.root = root
        self.source = source
        self._exists = exists
        self._is_dir = is_dir
        self.inspect_calls = 0

    def inspect(self, explicit_root: str | Path | None = None) -> FakeStatus:
        assert explicit_root is None
        self.inspect_calls += 1
        exists = self.root.exists() if self._exists is None else self._exists
        is_dir = self.root.is_dir() if self._is_dir is None else self._is_dir
        return FakeStatus(
            root=self.root,
            source=self.source,
            exists=exists,
            is_dir=is_dir,
            is_writable=False,
            config_path=self.root.parent / "config.json",
            default_root=self.root.parent / "default",
        )

    def services(self, core_version: str = "0.6.0") -> CoreBackupServices:
        return CoreBackupServices(
            inspect_workspace_root=cast(WorkspaceInspector, self.inspect),
            core_version=core_version,
        )


FIXED_TIME = datetime(2026, 8, 20, 17, 48, 12, 123456, tzinfo=timezone.utc)
EXPECTED_NAME = "pds-workspace-backup-20260820T174812123456Z"


def free_space(value: int):  # type: ignore[no-untyped-def]
    return lambda _path: SimpleNamespace(total=value * 2, used=value, free=value)


def test_backup_name_is_utc_and_windows_safe() -> None:
    eastern = timezone(-timedelta(hours=4))
    local = datetime(2026, 8, 20, 13, 48, 12, 123456, tzinfo=eastern)

    assert backup_name(local) == EXPECTED_NAME
    assert ":" not in backup_name(local)


def test_backup_name_rejects_naive_datetime() -> None:
    with pytest.raises(WorkspaceBackupManifestError, match="timezone-aware"):
        backup_name(datetime(2026, 8, 20, 17, 48, 12))


def test_required_space_uses_minimum_reserve_and_two_percent() -> None:
    assert required_backup_free_bytes(0) == BACKUP_MINIMUM_RESERVE_BYTES
    assert required_backup_free_bytes(1024) == 1024 + BACKUP_MINIMUM_RESERVE_BYTES

    large = 10 * 1024 * 1024 * 1024
    assert required_backup_free_bytes(large) == (
        large + ((large * 2 + 99) // 100)
    )


def test_inventory_is_complete_sorted_and_opaque(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    (root / ".pds").mkdir(parents=True)
    (root / "classes" / "future-module" / "empty").mkdir(parents=True)
    (root / "classes" / "future-module" / "opaque.bin").write_bytes(b"\x00\xffx")
    (root / ".hidden").write_text("secret-looking", encoding="utf-8")
    (root / "zero.dat").write_bytes(b"")

    inventory = inventory_workspace(root)

    assert inventory.directories == (
        ".pds",
        "classes",
        "classes/future-module",
        "classes/future-module/empty",
    )
    assert tuple(item.path for item in inventory.files) == (
        ".hidden",
        "classes/future-module/opaque.bin",
        "zero.dat",
    )
    assert tuple(item.size for item in inventory.files) == (14, 3, 0)
    assert inventory.total_bytes == 17


def test_inventory_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.write_text("do not copy", encoding="utf-8")
    link = root / "outside-link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(
        WorkspaceBackupUnsupportedEntryError,
        match="does not follow linked filesystem entry",
    ):
        inventory_workspace(root)


def _planned_backup(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "empty").mkdir()
    (root / "alpha.bin").write_bytes(b"alpha")
    destination = tmp_path / "backups"
    fake = FakeCoreBackup(root)
    required = required_backup_free_bytes(5)
    plan = plan_workspace_backup(
        destination,
        services=fake.services(),
        clock=lambda: FIXED_TIME,
        disk_usage_reader=free_space(required),
    )
    return root, destination, fake, plan


def test_plan_is_read_only_and_does_not_require_source_writability(
    tmp_path: Path,
) -> None:
    root, destination, fake, plan = _planned_backup(tmp_path)

    assert fake.inspect_calls == 1
    assert plan.workspace_root == root.resolve()
    assert plan.workspace_source == "saved_config"
    assert plan.destination_parent == destination.resolve()
    assert plan.final_backup_root == destination.resolve() / EXPECTED_NAME
    assert plan.backup_id == EXPECTED_NAME
    assert plan.destination_parent_exists is False
    assert plan.inventory.file_count == 1
    assert plan.inventory.directory_count == 1
    assert plan.inventory.total_bytes == 5
    assert not destination.exists()
    assert (root / "alpha.bin").read_bytes() == b"alpha"


def test_plan_refuses_missing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    fake = FakeCoreBackup(root, exists=False, is_dir=False)

    with pytest.raises(WorkspaceBackupSourceError, match="does not exist"):
        plan_workspace_backup(
            tmp_path / "backups",
            services=fake.services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


def test_plan_refuses_non_directory_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.write_text("not a directory", encoding="utf-8")
    fake = FakeCoreBackup(root, exists=True, is_dir=False)

    with pytest.raises(WorkspaceBackupSourceError, match="not a directory"):
        plan_workspace_backup(
            tmp_path / "backups",
            services=fake.services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


@pytest.mark.parametrize("relative", (".", "child", "child/grandchild"))
def test_plan_refuses_destination_at_or_inside_workspace(
    tmp_path: Path,
    relative: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    destination = root if relative == "." else root / relative

    with pytest.raises(WorkspaceBackupDestinationError, match="outside"):
        plan_workspace_backup(
            destination,
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


def test_plan_allows_safe_destination_parent_that_contains_workspace_sibling(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    plan = plan_workspace_backup(
        tmp_path,
        services=FakeCoreBackup(root).services(),
        clock=lambda: FIXED_TIME,
        disk_usage_reader=free_space(10**9),
    )

    assert plan.final_backup_root == tmp_path / EXPECTED_NAME


def test_plan_resolves_destination_alias_before_containment(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")

    with pytest.raises(WorkspaceBackupDestinationError, match="outside"):
        plan_workspace_backup(
            alias,
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


def test_plan_refuses_existing_final_backup_collision(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    destination = tmp_path / "backups"
    root.mkdir()
    destination.mkdir()
    (destination / EXPECTED_NAME).mkdir()

    with pytest.raises(WorkspaceBackupCollisionError, match="will not be overwritten"):
        plan_workspace_backup(
            destination,
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


def test_plan_refuses_insufficient_space_and_accepts_exact_threshold(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "payload").write_bytes(b"12345")
    required = required_backup_free_bytes(5)

    with pytest.raises(WorkspaceBackupSpaceError, match="Insufficient"):
        plan_workspace_backup(
            tmp_path / "backups",
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(required - 1),
        )

    plan = plan_workspace_backup(
        tmp_path / "backups",
        services=FakeCoreBackup(root).services(),
        clock=lambda: FIXED_TIME,
        disk_usage_reader=free_space(required),
    )
    assert plan.destination_free_bytes == required
    assert plan.required_free_bytes == required


def test_plan_refuses_destination_that_is_a_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    destination = tmp_path / "backups"
    destination.write_text("not a directory", encoding="utf-8")

    with pytest.raises(WorkspaceBackupDestinationError, match="not a directory"):
        plan_workspace_backup(
            destination,
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=free_space(10**9),
        )


def test_plan_reports_free_space_provider_failure(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    def fail(_path: str | os.PathLike[str]):
        raise OSError("synthetic disk query failure")

    with pytest.raises(WorkspaceBackupDestinationError, match="free space"):
        plan_workspace_backup(
            tmp_path / "backups",
            services=FakeCoreBackup(root).services(),
            clock=lambda: FIXED_TIME,
            disk_usage_reader=fail,
        )


def test_manifest_is_deterministic_portable_and_round_trips(tmp_path: Path) -> None:
    _root, _destination, _fake, plan = _planned_backup(tmp_path)
    digest = hashlib.sha256(b"alpha").hexdigest()
    manifest = create_workspace_backup_manifest(
        plan,
        (BackupFileEntry(path="alpha.bin", size=5, sha256=digest),),
    )

    first = serialize_workspace_backup_manifest(manifest)
    second = serialize_workspace_backup_manifest(manifest)
    parsed = parse_workspace_backup_manifest(first)

    assert first == second
    assert parsed == manifest
    assert manifest.record_type == BACKUP_MANIFEST_RECORD_TYPE
    assert manifest.schema_version == BACKUP_MANIFEST_SCHEMA_VERSION
    assert manifest.payload_root == BACKUP_PAYLOAD_ROOT
    assert manifest.exclusions == ()
    assert str(plan.workspace_root).encode() not in first
    assert b"saved_config" not in first
    assert workspace_backup_manifest_sha256(manifest) == (
        hashlib.sha256(first).hexdigest()
    )
    assert first.endswith(b"\n")


@pytest.mark.parametrize(
    "path",
    (
        r"folder\child.txt",
        r"..\outside.txt",
        "C:relative.txt",
        "file.txt:stream",
        "line\nbreak.txt",
    ),
)
def test_manifest_paths_reject_nonportable_or_control_syntax(path: str) -> None:
    with pytest.raises(WorkspaceBackupManifestError, match="path"):
        BackupFileEntry(path=path, size=0, sha256="0" * 64)


def test_manifest_file_entries_must_match_reviewed_inventory(tmp_path: Path) -> None:
    _root, _destination, _fake, plan = _planned_backup(tmp_path)
    digest = "0" * 64

    with pytest.raises(WorkspaceBackupManifestError, match="do not match"):
        create_workspace_backup_manifest(
            plan,
            (BackupFileEntry(path="different.bin", size=5, sha256=digest),),
        )


def test_manifest_parser_rejects_unknown_and_duplicate_fields(tmp_path: Path) -> None:
    _root, _destination, _fake, plan = _planned_backup(tmp_path)
    manifest = create_workspace_backup_manifest(
        plan,
        (
            BackupFileEntry(
                path="alpha.bin",
                size=5,
                sha256=hashlib.sha256(b"alpha").hexdigest(),
            ),
        ),
    )
    mapping = json.loads(serialize_workspace_backup_manifest(manifest))
    mapping["unexpected"] = True

    with pytest.raises(WorkspaceBackupManifestError, match="unknown field"):
        parse_workspace_backup_manifest(json.dumps(mapping))

    duplicate = '{"record_type":"x","record_type":"y"}'
    with pytest.raises(WorkspaceBackupManifestError, match="duplicate JSON object key"):
        parse_workspace_backup_manifest(duplicate)


def test_manifest_v1_refuses_nonempty_exclusions(tmp_path: Path) -> None:
    _root, _destination, _fake, plan = _planned_backup(tmp_path)
    manifest = create_workspace_backup_manifest(
        plan,
        (BackupFileEntry(path="alpha.bin", size=5, sha256="0" * 64),),
    )
    mapping = json.loads(serialize_workspace_backup_manifest(manifest))
    mapping["exclusions"] = ["*.tmp"]

    with pytest.raises(WorkspaceBackupManifestError, match="empty.*exclusions"):
        parse_workspace_backup_manifest(json.dumps(mapping))


def test_load_services_qualifies_core_before_import_and_exposes_reader_only() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    events: list[str] = []

    def version_lookup(distribution: str) -> str:
        events.append(f"version:{distribution}")
        return core.version

    module = SimpleNamespace(
        inspect_workspace_root=lambda explicit_root=None: None,
        ensure_workspace_root=lambda path, create=True: Path(path),
        save_workspace_root=lambda path: Path(path),
        clear_saved_workspace_root=lambda: False,
    )

    def importer(name: str) -> object:
        events.append(f"import:{name}")
        return module

    services = load_core_backup_services(
        manifest,
        version_lookup=version_lookup,
        module_importer=importer,
    )

    assert events == [f"version:{core.distribution}", "import:pds_core.workspace"]
    assert services.core_version == core.version
    assert not hasattr(services, "ensure_workspace_root")
    assert not hasattr(services, "save_workspace_root")
    assert not hasattr(services, "clear_saved_workspace_root")


def _creation_plan(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "workspace"
    (root / ".pds").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "future" / "module").mkdir(parents=True)
    (root / "alpha.bin").write_bytes(b"alpha")
    (root / "future" / "module" / "zero.dat").write_bytes(b"")
    destination = tmp_path / "backups"
    fake = FakeCoreBackup(root)
    required = required_backup_free_bytes(5)
    plan = plan_workspace_backup(
        destination,
        services=fake.services(),
        clock=lambda: FIXED_TIME,
        disk_usage_reader=free_space(required + 1024),
    )
    return root, destination, fake, plan, required


def test_create_backup_copies_opaque_tree_verifies_manifest_and_publishes(
    tmp_path: Path,
) -> None:
    root, destination, fake, plan, required = _creation_plan(tmp_path)
    source_before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    result = create_workspace_backup(
        plan,
        services=fake.services(),
        disk_usage_reader=free_space(required + 1024),
        staging_nonce_factory=lambda: "fixed",
        chunk_size=2,
    )

    assert result.final_backup_root == destination / EXPECTED_NAME
    assert result.final_backup_root.is_dir()
    assert result.manifest_path.is_file()
    assert (result.payload_root / "empty").is_dir()
    assert (result.payload_root / "future" / "module").is_dir()
    assert (result.payload_root / "alpha.bin").read_bytes() == b"alpha"
    assert (result.payload_root / "future" / "module" / "zero.dat").read_bytes() == b""
    assert parse_workspace_backup_manifest(result.manifest_path.read_bytes()) == (
        result.manifest
    )
    assert result.manifest_sha256 == hashlib.sha256(
        result.manifest_path.read_bytes()
    ).hexdigest()
    assert tuple(entry.path for entry in result.manifest.files) == (
        "alpha.bin",
        "future/module/zero.dat",
    )
    assert result.manifest.files[0].sha256 == hashlib.sha256(b"alpha").hexdigest()
    assert not list(destination.glob(".*.incomplete-*"))
    source_after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert source_after == source_before


def test_create_backup_rechecks_reviewed_source_before_destination_mutation(
    tmp_path: Path,
) -> None:
    root, destination, fake, plan, required = _creation_plan(tmp_path)
    (root / "late.bin").write_bytes(b"late")

    with pytest.raises(WorkspaceBackupDriftError, match="after backup preview"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
        )

    assert not destination.exists()


def test_create_backup_detects_same_size_source_change_after_copy(
    tmp_path: Path,
) -> None:
    root, destination, fake, plan, required = _creation_plan(tmp_path)

    def mutate(source_root: Path, _payload_root: Path) -> None:
        (source_root / "alpha.bin").write_bytes(b"bravo")

    with pytest.raises(WorkspaceBackupDriftError, match="changed while"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=mutate,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))
    assert (root / "alpha.bin").read_bytes() == b"bravo"


def test_create_backup_detects_added_source_entry_after_copy(tmp_path: Path) -> None:
    root, destination, fake, plan, required = _creation_plan(tmp_path)

    def mutate(source_root: Path, _payload_root: Path) -> None:
        (source_root / "added.bin").write_bytes(b"new")

    with pytest.raises(WorkspaceBackupDriftError, match="changed while"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=mutate,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_detects_removed_source_entry_after_copy(tmp_path: Path) -> None:
    root, destination, fake, plan, required = _creation_plan(tmp_path)

    def mutate(source_root: Path, _payload_root: Path) -> None:
        (source_root / "alpha.bin").unlink()

    with pytest.raises(WorkspaceBackupDriftError, match="changed while"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=mutate,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_detects_directory_change_after_copy(tmp_path: Path) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def mutate(source_root: Path, _payload_root: Path) -> None:
        (source_root / "new-empty-directory").mkdir()

    with pytest.raises(WorkspaceBackupDriftError, match="changed while"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            after_copy_hook=mutate,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_cleans_staging_after_copy_failure(tmp_path: Path) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def fail_copy(
        _source_root: Path,
        _payload_root: Path,
        relative: str,
        _chunk_size: int,
    ) -> BackupFileEntry:
        raise WorkspaceBackupCopyError(f"synthetic copy failure: {relative}")

    with pytest.raises(WorkspaceBackupCopyError, match="synthetic copy failure"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            file_copier=fail_copy,
        )

    assert destination.is_dir()
    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_wraps_filesystem_copy_failure_and_cleans_staging(
    tmp_path: Path,
) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def fail_copy(
        _source_root: Path,
        _payload_root: Path,
        _relative: str,
        _chunk_size: int,
    ) -> BackupFileEntry:
        raise OSError("synthetic disk-full style failure")

    with pytest.raises(WorkspaceBackupCopyError, match="filesystem error"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            file_copier=fail_copy,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_manifest_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.workspace_backup as backup

    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def fail_manifest(
        _staging_root: Path,
        _manifest: object,
    ) -> str:
        raise WorkspaceBackupVerificationError("synthetic manifest write failure")

    monkeypatch.setattr(backup, "_write_verified_manifest", fail_manifest)

    with pytest.raises(WorkspaceBackupVerificationError, match="manifest write"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_reports_staging_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.workspace_backup as backup

    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def fail_copy(
        _source_root: Path,
        _payload_root: Path,
        _relative: str,
        _chunk_size: int,
    ) -> BackupFileEntry:
        raise WorkspaceBackupCopyError("synthetic copy failure")

    def fail_cleanup(_path: Path) -> None:
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(backup.shutil, "rmtree", fail_cleanup)

    with pytest.raises(WorkspaceBackupCopyError, match="Incomplete staging remains"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            file_copier=fail_copy,
        )

    staging = destination / f".{EXPECTED_NAME}.incomplete-fixed"
    assert staging.is_dir()
    assert not (destination / EXPECTED_NAME).exists()


def test_create_backup_verifies_staged_bytes_independently(tmp_path: Path) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def corrupt_copy(
        _source_root: Path,
        payload_root: Path,
        relative: str,
        _chunk_size: int,
    ) -> BackupFileEntry:
        target = payload_root.joinpath(*relative.split("/"))
        target.write_bytes(b"wrong" if relative == "alpha.bin" else b"")
        expected_bytes = b"alpha" if relative == "alpha.bin" else b""
        return BackupFileEntry(
            path=relative,
            size=len(expected_bytes),
            sha256=hashlib.sha256(expected_bytes).hexdigest(),
        )

    with pytest.raises(WorkspaceBackupVerificationError, match="integrity"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            file_copier=corrupt_copy,
        )

    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_refuses_publication_collision_without_overwrite(
    tmp_path: Path,
) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def collide(_staging_root: Path, final_root: Path) -> None:
        final_root.mkdir()
        (final_root / "sentinel.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(WorkspaceBackupCollisionError, match="will not be overwritten"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            before_publish_hook=collide,
        )

    assert (destination / EXPECTED_NAME / "sentinel.txt").read_text(
        encoding="utf-8"
    ) == "preserve"
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_refuses_empty_publication_collision_without_overwrite(
    tmp_path: Path,
) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    def collide(_staging_root: Path, final_root: Path) -> None:
        final_root.mkdir()

    with pytest.raises(WorkspaceBackupCollisionError, match="will not be overwritten"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
            before_publish_hook=collide,
        )

    assert (destination / EXPECTED_NAME).is_dir()
    assert not tuple((destination / EXPECTED_NAME).iterdir())
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_rechecks_free_space_at_execution(tmp_path: Path) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)

    with pytest.raises(WorkspaceBackupSpaceError, match="Insufficient"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required - 1),
            staging_nonce_factory=lambda: "fixed",
        )

    # Destination parent may be created at the confirmed execution boundary,
    # but no staging or completed backup is allowed.
    assert destination.is_dir()
    assert not (destination / EXPECTED_NAME).exists()
    assert not list(destination.glob(".*.incomplete-*"))


def test_create_backup_refuses_changed_core_workspace_resolution(
    tmp_path: Path,
) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    fake.root = replacement

    with pytest.raises(WorkspaceBackupDriftError, match="resolved workspace changed"):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
        )

    assert not destination.exists()


def test_create_backup_preserves_preexisting_staging_collision(tmp_path: Path) -> None:
    _root, destination, fake, plan, required = _creation_plan(tmp_path)
    destination.mkdir()
    staging = destination / f".{EXPECTED_NAME}.incomplete-fixed"
    staging.mkdir()
    sentinel = staging / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(
        WorkspaceBackupCollisionError,
        match="staging path already exists",
    ):
        create_workspace_backup(
            plan,
            services=fake.services(),
            disk_usage_reader=free_space(required + 1024),
            staging_nonce_factory=lambda: "fixed",
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (destination / EXPECTED_NAME).exists()
