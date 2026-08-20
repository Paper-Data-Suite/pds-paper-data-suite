"""Suite-owned orchestration over the public Core workspace contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
)
from paper_data_suite.component_inspection import (
    DistributionVersionLookup,
    lookup_distribution_version,
)

ModuleImporter = Callable[[str], object]


class WorkspaceSetupError(RuntimeError):
    """Base class for bounded suite workspace-orchestration failures."""


class CoreWorkspaceQualificationError(WorkspaceSetupError):
    """Raised when the active Core installation is not suite-qualified."""


class CoreWorkspaceServiceError(WorkspaceSetupError):
    """Raised when a required public Core workspace service is unavailable."""


class WorkspaceValidationError(WorkspaceSetupError):
    """Raised when Core rejects a validate-only workspace operation."""


class WorkspaceEnvironmentOverrideError(WorkspaceSetupError):
    """Raised when PDS_WORKSPACE_ROOT prevents a requested selection."""


class WorkspaceMutationError(WorkspaceSetupError):
    """Raised when Core cannot initialize or reset workspace state."""


class WorkspacePartialSuccessError(WorkspaceMutationError):
    """Raised when initialization succeeded but selection could not finish."""

    def __init__(
        self,
        message: str,
        *,
        initialized_root: Path,
        resolved: WorkspaceObservation | None,
    ) -> None:
        super().__init__(message)
        self.initialized_root = initialized_root
        self.resolved = resolved


class WorkspacePresentationState(str, Enum):
    """Small suite presentation vocabulary over public Core workspace facts."""

    MISSING = "MISSING"
    EMPTY_DIRECTORY = "EMPTY_DIRECTORY"
    EXISTING_DIRECTORY = "EXISTING_DIRECTORY"
    INVALID = "INVALID"


class WorkspaceStatusLike(Protocol):
    """Public Core workspace-status fields consumed by suite orchestration."""

    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool
    config_path: Path
    default_root: Path


class WorkspaceInspector(Protocol):
    """Shape of Core's public workspace inspection callable."""

    def __call__(
        self,
        explicit_root: str | Path | None = None,
    ) -> WorkspaceStatusLike: ...


class WorkspaceEnsurer(Protocol):
    """Shape of Core's public workspace validation/initialization callable."""

    def __call__(
        self,
        path: str | Path,
        create: bool = True,
    ) -> Path: ...


class WorkspaceSaver(Protocol):
    """Shape of Core's public saved-workspace persistence callable."""

    def __call__(self, path: str | Path) -> Path: ...


class WorkspaceResetter(Protocol):
    """Shape of Core's public saved-workspace clearing callable."""

    def __call__(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class CoreWorkspaceServices:
    """Qualified public Core workspace services used by the suite."""

    inspect_workspace_root: WorkspaceInspector
    ensure_workspace_root: WorkspaceEnsurer
    save_workspace_root: WorkspaceSaver
    clear_saved_workspace_root: WorkspaceResetter


@dataclass(frozen=True, slots=True)
class WorkspaceObservation:
    """Teacher-facing bounded view of one Core-resolved workspace candidate."""

    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool
    config_path: Path
    default_root: Path
    state: WorkspacePresentationState
    reason: str


@dataclass(frozen=True, slots=True)
class WorkspaceSelectionResult:
    """Result of an explicit Core initialization plus saved selection."""

    observation: WorkspaceObservation
    created: bool
    saved: bool


@dataclass(frozen=True, slots=True)
class WorkspaceResetResult:
    """Result after clearing only Core's saved workspace preference."""

    cleared: bool
    observation: WorkspaceObservation


def _shared_core_component(
    manifest: ReleaseCompatibilityManifest,
) -> ComponentCompatibility:
    candidates = tuple(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    if len(candidates) != 1:
        raise CoreWorkspaceQualificationError(
            "The suite manifest does not identify exactly one shared Core component."
        )
    return candidates[0]


def _qualify_core(
    manifest: ReleaseCompatibilityManifest,
    *,
    version_lookup: DistributionVersionLookup,
) -> ComponentCompatibility:
    component = _shared_core_component(manifest)
    try:
        observed = lookup_distribution_version(component.distribution, version_lookup)
    except (OSError, TypeError, ValueError) as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreWorkspaceQualificationError(
            f"Could not inspect {component.distribution}: {message}"
        ) from error

    if observed != component.version:
        actual = observed or "not installed"
        raise CoreWorkspaceQualificationError(
            f"Installed {component.distribution} is {actual}; this suite qualifies "
            f"exactly {component.version}. Use the verified Paper Data Suite "
            "bootstrap/update workflow to restore the qualified environment."
        )
    return component


def _required_callable(module: object, name: str) -> object:
    value = getattr(module, name, None)
    if not callable(value):
        raise CoreWorkspaceServiceError(
            f"Suite-qualified Core does not expose public callable "
            f"pds_core.workspace.{name}."
        )
    return value


def load_core_workspace_services(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
) -> CoreWorkspaceServices:
    """Qualify Core before importing its public workspace service module."""
    active_manifest = manifest or load_release_compatibility_manifest()
    _qualify_core(active_manifest, version_lookup=version_lookup)

    try:
        module = module_importer("pds_core.workspace")
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreWorkspaceServiceError(
            f"Could not import public Core workspace services: {message}"
        ) from error

    return CoreWorkspaceServices(
        inspect_workspace_root=cast(
            WorkspaceInspector,
            _required_callable(module, "inspect_workspace_root"),
        ),
        ensure_workspace_root=cast(
            WorkspaceEnsurer,
            _required_callable(module, "ensure_workspace_root"),
        ),
        save_workspace_root=cast(
            WorkspaceSaver,
            _required_callable(module, "save_workspace_root"),
        ),
        clear_saved_workspace_root=cast(
            WorkspaceResetter,
            _required_callable(module, "clear_saved_workspace_root"),
        ),
    )


def _status_fields(status: WorkspaceStatusLike) -> tuple[
    Path,
    str,
    bool,
    bool,
    bool,
    Path,
    Path,
]:
    try:
        root = Path(status.root)
        source = status.source
        exists = status.exists
        is_dir = status.is_dir
        is_writable = status.is_writable
        config_path = Path(status.config_path)
        default_root = Path(status.default_root)
    except (AttributeError, TypeError, ValueError) as error:
        raise CoreWorkspaceServiceError(
            "Core returned an invalid workspace status result."
        ) from error

    if not isinstance(source, str) or not source.strip():
        raise CoreWorkspaceServiceError(
            "Core returned an invalid workspace selection source."
        )
    if not all(isinstance(value, bool) for value in (exists, is_dir, is_writable)):
        raise CoreWorkspaceServiceError(
            "Core returned invalid workspace access flags."
        )
    return (
        root,
        source,
        exists,
        is_dir,
        is_writable,
        config_path,
        default_root,
    )


def _directory_has_entries(root: Path) -> bool:
    try:
        next(root.iterdir())
    except StopIteration:
        return False
    except OSError as error:
        raise WorkspaceValidationError(
            f"Could not inspect whether workspace directory is empty: {error}"
        ) from error
    return True


def _presentation_state(
    *,
    root: Path,
    exists: bool,
    is_dir: bool,
    is_writable: bool,
) -> tuple[WorkspacePresentationState, str]:
    if not exists:
        if is_writable:
            return (
                WorkspacePresentationState.MISSING,
                "Workspace directory has not been created yet.",
            )
        return (
            WorkspacePresentationState.INVALID,
            "Workspace directory does not exist and its parent is not writable.",
        )
    if not is_dir:
        return (
            WorkspacePresentationState.INVALID,
            "Workspace path exists but is not a directory.",
        )
    if not is_writable:
        return (
            WorkspacePresentationState.INVALID,
            "Workspace directory is not writable according to Core.",
        )
    if _directory_has_entries(root):
        return (
            WorkspacePresentationState.EXISTING_DIRECTORY,
            "Workspace candidate is an existing non-empty directory.",
        )
    return (
        WorkspacePresentationState.EMPTY_DIRECTORY,
        "Workspace candidate is an existing empty directory.",
    )


def observe_workspace(
    explicit_root: str | Path | None = None,
    *,
    services: CoreWorkspaceServices | None = None,
) -> WorkspaceObservation:
    """Inspect one workspace candidate without initializing or saving it."""
    active_services = services or load_core_workspace_services()
    try:
        status = active_services.inspect_workspace_root(explicit_root)
    except WorkspaceSetupError:
        raise
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreWorkspaceServiceError(
            f"Core could not inspect the workspace: {message}"
        ) from error

    (
        root,
        source,
        exists,
        is_dir,
        is_writable,
        config_path,
        default_root,
    ) = _status_fields(status)
    state, reason = _presentation_state(
        root=root,
        exists=exists,
        is_dir=is_dir,
        is_writable=is_writable,
    )
    return WorkspaceObservation(
        root=root,
        source=source,
        exists=exists,
        is_dir=is_dir,
        is_writable=is_writable,
        config_path=config_path,
        default_root=default_root,
        state=state,
        reason=reason,
    )


def validate_workspace(
    explicit_root: str | Path | None = None,
    *,
    services: CoreWorkspaceServices | None = None,
) -> WorkspaceObservation:
    """Validate an existing candidate through Core without saving or creating it."""
    active_services = services or load_core_workspace_services()
    before = observe_workspace(explicit_root, services=active_services)
    try:
        active_services.ensure_workspace_root(before.root, create=False)
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceValidationError(
            f"Core rejected workspace candidate {before.root}: {message}"
        ) from error
    return observe_workspace(explicit_root, services=active_services)


def _safe_current_observation(
    services: CoreWorkspaceServices,
) -> WorkspaceObservation | None:
    try:
        return observe_workspace(services=services)
    except WorkspaceSetupError:
        return None


def initialize_resolved_workspace(
    *,
    services: CoreWorkspaceServices | None = None,
) -> WorkspaceSelectionResult:
    """Initialize the current Core-resolved workspace without saving a preference."""
    active_services = services or load_core_workspace_services()
    current = observe_workspace(services=active_services)
    created = not current.exists
    try:
        initialized_root = active_services.ensure_workspace_root(
            current.root,
            create=True,
        )
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceMutationError(
            f"Core could not initialize workspace {current.root}: {message}"
        ) from error

    resolved = observe_workspace(services=active_services)
    if resolved.root != Path(initialized_root):
        raise WorkspaceMutationError(
            "Core initialized the workspace, but the active resolved workspace "
            f"is {resolved.root} instead of {initialized_root}."
        )
    return WorkspaceSelectionResult(
        observation=resolved,
        created=created,
        saved=False,
    )


def set_workspace(
    path: str | Path,
    *,
    services: CoreWorkspaceServices | None = None,
) -> WorkspaceSelectionResult:
    """Initialize one candidate through Core and save it through Core."""
    active_services = services or load_core_workspace_services()
    current = observe_workspace(services=active_services)
    candidate = observe_workspace(path, services=active_services)

    if current.source == "environment" and current.root != candidate.root:
        raise WorkspaceEnvironmentOverrideError(
            "PDS_WORKSPACE_ROOT currently controls the active workspace at "
            f"{current.root}. Remove or change that environment override before "
            f"selecting {candidate.root}."
        )

    created = not candidate.exists
    try:
        initialized_root = active_services.ensure_workspace_root(
            candidate.root,
            create=True,
        )
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceMutationError(
            f"Core could not initialize workspace {candidate.root}: {message}"
        ) from error

    try:
        saved_root = active_services.save_workspace_root(initialized_root)
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspacePartialSuccessError(
            "Core initialized the workspace, but the saved workspace preference "
            f"could not be updated: {message}",
            initialized_root=Path(initialized_root),
            resolved=_safe_current_observation(active_services),
        ) from error

    resolved = observe_workspace(services=active_services)
    if resolved.root != Path(saved_root) or resolved.root != Path(initialized_root):
        raise WorkspacePartialSuccessError(
            "Core saved the workspace preference, but the active resolved workspace "
            f"is {resolved.root} instead of {initialized_root}.",
            initialized_root=Path(initialized_root),
            resolved=resolved,
        )

    return WorkspaceSelectionResult(
        observation=resolved,
        created=created,
        saved=True,
    )


def reset_workspace(
    *,
    services: CoreWorkspaceServices | None = None,
) -> WorkspaceResetResult:
    """Clear only Core's saved workspace preference and report actual resolution."""
    active_services = services or load_core_workspace_services()
    try:
        cleared = active_services.clear_saved_workspace_root()
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceMutationError(
            f"Core could not clear the saved workspace preference: {message}"
        ) from error
    return WorkspaceResetResult(
        cleared=cleared,
        observation=observe_workspace(services=active_services),
    )


__all__ = (
    "CoreWorkspaceQualificationError",
    "CoreWorkspaceServiceError",
    "CoreWorkspaceServices",
    "WorkspaceEnvironmentOverrideError",
    "WorkspaceMutationError",
    "WorkspaceObservation",
    "WorkspacePartialSuccessError",
    "WorkspacePresentationState",
    "WorkspaceResetResult",
    "WorkspaceSelectionResult",
    "WorkspaceSetupError",
    "WorkspaceValidationError",
    "initialize_resolved_workspace",
    "load_core_workspace_services",
    "observe_workspace",
    "reset_workspace",
    "set_workspace",
    "validate_workspace",
)
