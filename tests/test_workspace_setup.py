from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from paper_data_suite.compatibility import load_release_compatibility_manifest
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    CoreWorkspaceServiceError,
    CoreWorkspaceServices,
    WorkspaceEnvironmentOverrideError,
    WorkspaceMutationError,
    WorkspacePartialSuccessError,
    WorkspacePresentationState,
    WorkspaceValidationError,
    load_core_workspace_services,
    observe_workspace,
    reset_workspace,
    set_workspace,
    validate_workspace,
)


@dataclass
class FakeStatus:
    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool
    config_path: Path
    default_root: Path


class FakeCoreWorkspace:
    def __init__(
        self,
        tmp_path: Path,
        *,
        current_root: Path | None = None,
        source: str = "default",
    ) -> None:
        self.tmp_path = tmp_path
        self.default_root = tmp_path / "default-workspace"
        self.config_path = tmp_path / "config.json"
        self.current_root = current_root or self.default_root
        self.source = source
        self.ensure_calls: list[tuple[Path, bool]] = []
        self.save_calls: list[Path] = []
        self.reset_calls = 0
        self.fail_ensure: Exception | None = None
        self.fail_save: Exception | None = None
        self.fail_reset: Exception | None = None
        self.force_post_save_root: Path | None = None

    def inspect(self, explicit_root: str | Path | None = None) -> FakeStatus:
        root = (
            Path(explicit_root).resolve()
            if explicit_root is not None
            else self.current_root
        )
        source = "explicit" if explicit_root is not None else self.source
        exists = root.exists()
        is_dir = root.is_dir() if exists else False
        writable = root.parent.exists() if not exists else is_dir
        return FakeStatus(
            root=root,
            source=source,
            exists=exists,
            is_dir=is_dir,
            is_writable=writable,
            config_path=self.config_path,
            default_root=self.default_root,
        )

    def ensure(self, path: str | Path, create: bool = True) -> Path:
        root = Path(path)
        self.ensure_calls.append((root, create))
        if self.fail_ensure is not None:
            raise self.fail_ensure
        if not root.exists():
            if not create:
                raise RuntimeError("does not exist")
            root.mkdir(parents=True)
        if not root.is_dir():
            raise RuntimeError("not a directory")
        return root

    def save(self, path: str | Path) -> Path:
        root = Path(path)
        self.save_calls.append(root)
        if self.fail_save is not None:
            raise self.fail_save
        if self.source != "environment":
            self.current_root = self.force_post_save_root or root
            self.source = "saved_config"
        return root

    def reset(self) -> bool:
        self.reset_calls += 1
        if self.fail_reset is not None:
            raise self.fail_reset
        if self.source == "saved_config":
            self.current_root = self.default_root
            self.source = "default"
            return True
        return False

    def services(self) -> CoreWorkspaceServices:
        return CoreWorkspaceServices(
            inspect_workspace_root=self.inspect,
            ensure_workspace_root=self.ensure,
            save_workspace_root=self.save,
            clear_saved_workspace_root=self.reset,
        )


def test_load_services_qualifies_core_before_import() -> None:
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

    load_core_workspace_services(
        manifest,
        version_lookup=version_lookup,
        module_importer=importer,
    )

    assert events == [
        f"version:{core.distribution}",
        "import:pds_core.workspace",
    ]


def test_load_services_refuses_wrong_core_before_import() -> None:
    imported = False

    def importer(name: str) -> object:
        nonlocal imported
        imported = True
        return SimpleNamespace()

    with pytest.raises(CoreWorkspaceQualificationError, match="qualifies exactly"):
        load_core_workspace_services(
            version_lookup=lambda _distribution: "0.6.99",
            module_importer=importer,
        )

    assert imported is False


def test_load_services_refuses_missing_core_before_import() -> None:
    imported = False

    def importer(name: str) -> object:
        nonlocal imported
        imported = True
        return SimpleNamespace()

    from importlib import metadata

    def missing(distribution: str) -> str:
        raise metadata.PackageNotFoundError(distribution)

    with pytest.raises(CoreWorkspaceQualificationError, match="not installed"):
        load_core_workspace_services(
            version_lookup=missing,
            module_importer=importer,
        )

    assert imported is False


def test_load_services_requires_public_callable() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    module = SimpleNamespace(
        inspect_workspace_root=lambda explicit_root=None: None,
        ensure_workspace_root=lambda path, create=True: Path(path),
        save_workspace_root=lambda path: Path(path),
    )

    with pytest.raises(CoreWorkspaceServiceError, match="clear_saved_workspace_root"):
        load_core_workspace_services(
            manifest,
            version_lookup=lambda _distribution: core.version,
            module_importer=lambda _name: module,
        )


def test_observe_missing_writable_candidate(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "missing"

    observation = observe_workspace(candidate, services=fake.services())

    assert observation.root == candidate.resolve()
    assert observation.state is WorkspacePresentationState.MISSING
    assert observation.exists is False


def test_observe_empty_directory_is_not_invalid(tmp_path: Path) -> None:
    candidate = tmp_path / "empty"
    candidate.mkdir()
    fake = FakeCoreWorkspace(tmp_path)

    observation = observe_workspace(candidate, services=fake.services())

    assert observation.state is WorkspacePresentationState.EMPTY_DIRECTORY
    assert observation.reason == "Workspace candidate is an existing empty directory."


def test_observe_nonempty_directory_without_reading_file_contents(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "existing"
    candidate.mkdir()
    content = candidate / "student-evidence.txt"
    content.write_text("sensitive synthetic content", encoding="utf-8")
    fake = FakeCoreWorkspace(tmp_path)

    observation = observe_workspace(candidate, services=fake.services())

    assert observation.state is WorkspacePresentationState.EXISTING_DIRECTORY
    assert content.read_text(encoding="utf-8") == "sensitive synthetic content"


def test_observe_existing_file_is_invalid(tmp_path: Path) -> None:
    candidate = tmp_path / "not-directory"
    candidate.write_text("content", encoding="utf-8")
    fake = FakeCoreWorkspace(tmp_path)

    observation = observe_workspace(candidate, services=fake.services())

    assert observation.state is WorkspacePresentationState.INVALID
    assert "not a directory" in observation.reason


def test_observe_rejects_malformed_status(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    services = fake.services()
    malformed = cast(
        object,
        SimpleNamespace(
            root=tmp_path,
            source="",
            exists=True,
            is_dir=True,
            is_writable=True,
            config_path=tmp_path / "config.json",
            default_root=tmp_path / "default",
        ),
    )
    broken = CoreWorkspaceServices(
        inspect_workspace_root=cast(
            object,
            lambda explicit_root=None: malformed,
        ),
        ensure_workspace_root=services.ensure_workspace_root,
        save_workspace_root=services.save_workspace_root,
        clear_saved_workspace_root=services.clear_saved_workspace_root,
    )

    with pytest.raises(CoreWorkspaceServiceError, match="selection source"):
        observe_workspace(services=broken)


def test_validate_missing_candidate_does_not_create_or_save(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "missing"

    with pytest.raises(WorkspaceValidationError, match="does not exist"):
        validate_workspace(candidate, services=fake.services())

    assert fake.ensure_calls == [(candidate.resolve(), False)]
    assert fake.save_calls == []
    assert not candidate.exists()


def test_validate_existing_empty_candidate_does_not_initialize_or_save(
    tmp_path: Path,
) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "empty"
    candidate.mkdir()

    observation = validate_workspace(candidate, services=fake.services())

    assert observation.state is WorkspacePresentationState.EMPTY_DIRECTORY
    assert fake.ensure_calls == [(candidate.resolve(), False)]
    assert fake.save_calls == []
    assert tuple(candidate.iterdir()) == ()


def test_set_missing_candidate_initializes_saves_and_reinspects(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "new-workspace"

    result = set_workspace(candidate, services=fake.services())

    assert result.created is True
    assert result.saved is True
    assert result.observation.root == candidate.resolve()
    assert result.observation.source == "saved_config"
    assert candidate.is_dir()
    assert fake.ensure_calls == [(candidate.resolve(), True)]
    assert fake.save_calls == [candidate.resolve()]


def test_set_existing_directory_preserves_existing_files(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "existing"
    candidate.mkdir()
    preserved = candidate / "preserved.txt"
    preserved.write_text("keep", encoding="utf-8")

    result = set_workspace(candidate, services=fake.services())

    assert result.created is False
    assert preserved.read_text(encoding="utf-8") == "keep"


def test_set_refuses_different_path_under_environment_override(tmp_path: Path) -> None:
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    fake = FakeCoreWorkspace(
        tmp_path,
        current_root=environment_root.resolve(),
        source="environment",
    )
    candidate = tmp_path / "candidate"

    with pytest.raises(WorkspaceEnvironmentOverrideError, match="PDS_WORKSPACE_ROOT"):
        set_workspace(candidate, services=fake.services())

    assert fake.ensure_calls == []
    assert fake.save_calls == []
    assert not candidate.exists()


def test_set_same_path_under_environment_override_is_allowed(tmp_path: Path) -> None:
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    fake = FakeCoreWorkspace(
        tmp_path,
        current_root=environment_root.resolve(),
        source="environment",
    )

    result = set_workspace(environment_root, services=fake.services())

    assert result.observation.root == environment_root.resolve()
    assert result.observation.source == "environment"
    assert fake.save_calls == [environment_root.resolve()]


def test_set_initialization_failure_does_not_save(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    fake.fail_ensure = PermissionError("denied")

    with pytest.raises(WorkspaceMutationError, match="could not initialize"):
        set_workspace(tmp_path / "candidate", services=fake.services())

    assert fake.save_calls == []


def test_set_save_failure_reports_partial_success(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    fake.fail_save = PermissionError("config denied")
    candidate = tmp_path / "candidate"

    with pytest.raises(WorkspacePartialSuccessError) as caught:
        set_workspace(candidate, services=fake.services())

    assert candidate.is_dir()
    assert caught.value.initialized_root == candidate.resolve()
    assert caught.value.resolved is not None


def test_set_post_save_resolution_mismatch_reports_partial_success(
    tmp_path: Path,
) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    candidate = tmp_path / "candidate"
    other = tmp_path / "other"
    other.mkdir()
    fake.force_post_save_root = other.resolve()

    with pytest.raises(WorkspacePartialSuccessError, match="active resolved workspace"):
        set_workspace(candidate, services=fake.services())

    assert candidate.is_dir()
    assert fake.save_calls == [candidate.resolve()]


def test_reset_clears_only_saved_preference_and_reinspects(tmp_path: Path) -> None:
    saved = tmp_path / "saved"
    saved.mkdir()
    preserved = saved / "keep.txt"
    preserved.write_text("keep", encoding="utf-8")
    fake = FakeCoreWorkspace(
        tmp_path,
        current_root=saved.resolve(),
        source="saved_config",
    )

    result = reset_workspace(services=fake.services())

    assert result.cleared is True
    assert result.observation.source == "default"
    assert preserved.read_text(encoding="utf-8") == "keep"
    assert fake.reset_calls == 1


def test_reset_under_environment_override_leaves_environment_active(
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / "environment"
    environment_root.mkdir()
    fake = FakeCoreWorkspace(
        tmp_path,
        current_root=environment_root.resolve(),
        source="environment",
    )

    result = reset_workspace(services=fake.services())

    assert result.cleared is False
    assert result.observation.root == environment_root.resolve()
    assert result.observation.source == "environment"


def test_reset_failure_is_bounded(tmp_path: Path) -> None:
    fake = FakeCoreWorkspace(tmp_path)
    fake.fail_reset = PermissionError("config denied")

    with pytest.raises(WorkspaceMutationError, match="could not clear"):
        reset_workspace(services=fake.services())


def test_initialize_resolved_environment_workspace_does_not_save_preference(
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / "environment"
    fake = FakeCoreWorkspace(
        tmp_path,
        current_root=environment_root.resolve(),
        source="environment",
    )

    from paper_data_suite.workspace_setup import initialize_resolved_workspace

    result = initialize_resolved_workspace(services=fake.services())

    assert result.created is True
    assert result.saved is False
    assert result.observation.root == environment_root.resolve()
    assert result.observation.source == "environment"
    assert environment_root.is_dir()
    assert fake.ensure_calls == [(environment_root.resolve(), True)]
    assert fake.save_calls == []

