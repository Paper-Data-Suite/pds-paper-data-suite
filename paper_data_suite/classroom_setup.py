"""Read-only assessment for guided shared classroom setup.

This module is a suite-owned orchestration layer over public, suite-qualified
PDS Core services.  It deliberately performs no setup mutation while loading
Core services or assessing the currently resolved workspace.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.compatibility import ReleaseCompatibilityManifest
from paper_data_suite.component_inspection import DistributionVersionLookup
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    CoreWorkspaceServiceError,
    CoreWorkspaceServices,
    load_core_workspace_services,
)

ModuleImporter = Callable[[str], object]


class ClassroomSetupError(RuntimeError):
    """Base class for bounded guided classroom-setup failures."""


class CoreClassroomServiceError(ClassroomSetupError):
    """Raised when a required public Core classroom service is unavailable."""


class ClassroomSetupAssessmentError(ClassroomSetupError):
    """Raised when current Core-owned shared state cannot be trusted."""


class ClassroomWorkspaceError(ClassroomSetupAssessmentError):
    """Raised when the currently resolved workspace is not usable for setup."""


class WorkspaceStatusLike(Protocol):
    """Public Core workspace status fields consumed during assessment."""

    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool


class SchoolYearStateLike(Protocol):
    """Public Core school-year state fields consumed during assessment."""

    active_school_year: str
    opened_at: datetime
    closed_at: datetime | None


class ClassFolderLike(Protocol):
    """Public Core class-folder fields consumed during assessment."""

    class_id: str
    class_dir: Path
    roster_path: Path
    metadata_path: Path


class ClassMetadataLike(Protocol):
    """Public Core class metadata fields consumed during assessment."""

    class_id: str
    school_year: str
    module_details: Mapping[str, object]


class StudentRecordLike(Protocol):
    """Public Core roster student fields used only for bounded counts."""

    student_id: str


class RosterLike(Protocol):
    """Public Core roster fields consumed during assessment."""

    class_id: str
    students: Sequence[StudentRecordLike]
    columns: Sequence[str]


class StandardsLibraryLike(Protocol):
    """Public Core standards-library fields consumed during assessment."""

    standards: Sequence[object]
    profiles: Sequence[object]


class StarterStandardsPackLike(Protocol):
    """Public Core starter-pack metadata fields consumed during assessment."""

    pack_id: str
    title: str
    source: str
    grade_bands: Sequence[str]
    courses: Sequence[str]
    standard_count: int
    profile_count: int


class AcademicPeriodCalendarLike(Protocol):
    """Public Core Academic Period calendar fields consumed during assessment."""

    school_year: str
    calendar_revision: int
    periods: Sequence[object]


class WorkspaceInspector(Protocol):
    def __call__(
        self,
        explicit_root: str | Path | None = None,
    ) -> WorkspaceStatusLike: ...


class SchoolYearLoader(Protocol):
    def __call__(self, workspace_root: str | Path) -> SchoolYearStateLike | None: ...


class ClassFolderLister(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        *,
        require_roster: bool = False,
        load_rosters: bool = False,
        require_metadata: bool = False,
        load_metadata: bool = False,
    ) -> tuple[ClassFolderLike, ...]: ...


class ClassMetadataLoader(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        class_id: str,
    ) -> ClassMetadataLike: ...


class ClassRosterLoader(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        class_id: str,
    ) -> RosterLike: ...


class WorkspaceStandardsLoader(Protocol):
    def __call__(self, workspace_root: str | Path) -> StandardsLibraryLike: ...


class StarterStandardsPackLister(Protocol):
    def __call__(self) -> tuple[StarterStandardsPackLike, ...]: ...


class CurrentAcademicPeriodCalendarLoader(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        school_year: str,
    ) -> AcademicPeriodCalendarLike | None: ...


class CurrentAcademicPeriodRevisionGetter(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        school_year: str,
    ) -> int | None: ...


@dataclass(frozen=True, slots=True)
class CoreClassroomServices:
    """Qualified public Core services used by the read-only setup assessment."""

    inspect_workspace_root: WorkspaceInspector
    load_school_year_state: SchoolYearLoader
    list_class_folders: ClassFolderLister
    load_class_metadata_for_class: ClassMetadataLoader
    load_class_roster: ClassRosterLoader
    load_workspace_standards_library: WorkspaceStandardsLoader
    list_starter_standards_packs: StarterStandardsPackLister
    load_current_academic_period_calendar: CurrentAcademicPeriodCalendarLoader
    get_current_academic_period_calendar_revision: CurrentAcademicPeriodRevisionGetter


@dataclass(frozen=True, slots=True)
class ClassSetupAssessment:
    """Bounded read-only status for one Core-valid class folder."""

    class_id: str
    metadata: ClassMetadataLike | None
    roster: RosterLike | None

    @property
    def has_metadata(self) -> bool:
        return self.metadata is not None

    @property
    def has_roster(self) -> bool:
        return self.roster is not None

    @property
    def student_count(self) -> int | None:
        if self.roster is None:
            return None
        return len(self.roster.students)


@dataclass(frozen=True, slots=True)
class SharedSetupAssessment:
    """Read-only Core-derived shared classroom state before teacher input."""

    workspace_root: Path
    workspace_source: str
    school_year_state: SchoolYearStateLike | None
    classes: tuple[ClassSetupAssessment, ...]
    standards_library: StandardsLibraryLike
    starter_standards_packs: tuple[StarterStandardsPackLike, ...]
    academic_period_calendar: AcademicPeriodCalendarLike | None
    academic_period_revision: int | None

    @property
    def active_school_year(self) -> str | None:
        state = self.school_year_state
        if state is None or state.closed_at is not None:
            return None
        return state.active_school_year

    @property
    def standards_count(self) -> int:
        return len(self.standards_library.standards)

    @property
    def standards_profile_count(self) -> int:
        return len(self.standards_library.profiles)


def _required_callable(module: object, module_name: str, name: str) -> object:
    value = getattr(module, name, None)
    if not callable(value):
        raise CoreClassroomServiceError(
            "Suite-qualified Core does not expose public callable "
            f"{module_name}.{name}."
        )
    return value


def _import_core_module(module_name: str, module_importer: ModuleImporter) -> object:
    try:
        return module_importer(module_name)
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreClassroomServiceError(
            f"Could not import public Core setup services from {module_name}: {message}"
        ) from error


def load_core_classroom_services(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
) -> CoreClassroomServices:
    """Qualify Core exactly, then load only public UI-neutral setup services.

    Qualification is delegated to the suite's existing workspace integration,
    so this workflow cannot accept a merely package-compatible but unqualified
    Core release.  No setup state is read or written by this loader.
    """
    try:
        workspace_services: CoreWorkspaceServices = load_core_workspace_services(
            manifest,
            version_lookup=version_lookup,
            module_importer=module_importer,
        )
    except (CoreWorkspaceQualificationError, CoreWorkspaceServiceError):
        raise

    school_years = _import_core_module("pds_core.school_years", module_importer)
    classes = _import_core_module("pds_core.classes", module_importer)
    class_metadata = _import_core_module("pds_core.class_metadata", module_importer)
    standards = _import_core_module("pds_core.standards", module_importer)
    starter_standards = _import_core_module(
        "pds_core.starter_standards",
        module_importer,
    )
    academic_period_storage = _import_core_module(
        "pds_core.academic_period_storage",
        module_importer,
    )

    return CoreClassroomServices(
        inspect_workspace_root=workspace_services.inspect_workspace_root,
        load_school_year_state=cast(
            SchoolYearLoader,
            _required_callable(
                school_years,
                "pds_core.school_years",
                "load_school_year_state",
            ),
        ),
        list_class_folders=cast(
            ClassFolderLister,
            _required_callable(classes, "pds_core.classes", "list_class_folders"),
        ),
        load_class_metadata_for_class=cast(
            ClassMetadataLoader,
            _required_callable(
                class_metadata,
                "pds_core.class_metadata",
                "load_class_metadata_for_class",
            ),
        ),
        load_class_roster=cast(
            ClassRosterLoader,
            _required_callable(classes, "pds_core.classes", "load_class_roster"),
        ),
        load_workspace_standards_library=cast(
            WorkspaceStandardsLoader,
            _required_callable(
                standards,
                "pds_core.standards",
                "load_workspace_standards_library",
            ),
        ),
        list_starter_standards_packs=cast(
            StarterStandardsPackLister,
            _required_callable(
                starter_standards,
                "pds_core.starter_standards",
                "list_starter_standards_packs",
            ),
        ),
        load_current_academic_period_calendar=cast(
            CurrentAcademicPeriodCalendarLoader,
            _required_callable(
                academic_period_storage,
                "pds_core.academic_period_storage",
                "load_current_academic_period_calendar",
            ),
        ),
        get_current_academic_period_calendar_revision=cast(
            CurrentAcademicPeriodRevisionGetter,
            _required_callable(
                academic_period_storage,
                "pds_core.academic_period_storage",
                "get_current_academic_period_calendar_revision",
            ),
        ),
    )


def _workspace_for_assessment(services: CoreClassroomServices) -> WorkspaceStatusLike:
    try:
        status = services.inspect_workspace_root()
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise ClassroomWorkspaceError(
            f"Core could not inspect the currently resolved workspace: {message}"
        ) from error

    try:
        root = Path(status.root)
        source = status.source
        exists = status.exists
        is_dir = status.is_dir
        is_writable = status.is_writable
    except (AttributeError, TypeError, ValueError) as error:
        raise ClassroomWorkspaceError(
            "Core returned an invalid workspace status result."
        ) from error

    if not isinstance(source, str) or not source.strip():
        raise ClassroomWorkspaceError(
            "Core returned an invalid workspace resolution source."
        )
    if not all(isinstance(value, bool) for value in (exists, is_dir, is_writable)):
        raise ClassroomWorkspaceError("Core returned invalid workspace access flags.")
    if not exists:
        raise ClassroomWorkspaceError(
            f"The currently resolved workspace does not exist: {root}. "
            "Run 'pds workspace setup' first."
        )
    if not is_dir:
        raise ClassroomWorkspaceError(
            f"The currently resolved workspace is not a directory: {root}. "
            "Run 'pds workspace setup' to select a usable workspace."
        )
    if not is_writable:
        raise ClassroomWorkspaceError(
            f"The currently resolved workspace is not writable: {root}. "
            "Fix workspace access or run 'pds workspace setup'."
        )
    return status


def _bounded_core_failure(area: str, error: Exception) -> ClassroomSetupAssessmentError:
    message = str(error)[:500] or error.__class__.__name__
    return ClassroomSetupAssessmentError(
        f"Existing Core {area} state could not be validated: {message}"
    )


def _assess_classes(
    workspace_root: Path,
    services: CoreClassroomServices,
) -> tuple[ClassSetupAssessment, ...]:
    try:
        folders = services.list_class_folders(workspace_root)
    except Exception as error:
        raise _bounded_core_failure("class-folder", error) from error

    assessed: list[ClassSetupAssessment] = []
    for folder in folders:
        try:
            class_id = folder.class_id
            metadata_path = Path(folder.metadata_path)
            roster_path = Path(folder.roster_path)
        except (AttributeError, TypeError, ValueError) as error:
            raise ClassroomSetupAssessmentError(
                "Core returned an invalid class-folder result."
            ) from error

        metadata_value: ClassMetadataLike | None = None
        if metadata_path.is_file():
            try:
                metadata_value = services.load_class_metadata_for_class(
                    workspace_root,
                    class_id,
                )
            except Exception as error:
                raise _bounded_core_failure(
                    f"class metadata for {class_id!r}",
                    error,
                ) from error

        roster_value: RosterLike | None = None
        if roster_path.is_file():
            try:
                roster_value = services.load_class_roster(workspace_root, class_id)
            except Exception as error:
                raise _bounded_core_failure(
                    f"roster for class {class_id!r}",
                    error,
                ) from error

        assessed.append(
            ClassSetupAssessment(
                class_id=class_id,
                metadata=metadata_value,
                roster=roster_value,
            )
        )
    return tuple(assessed)


def assess_shared_setup(
    *,
    services: CoreClassroomServices | None = None,
) -> SharedSetupAssessment:
    """Read current shared Core state without performing setup mutation.

    The workspace is inspected but not initialized or re-selected.  Existing
    canonical records are loaded only through public Core readers.  Any
    malformed or internally inconsistent state aborts assessment instead of
    allowing a guided setup plan to be constructed on top of it.
    """
    active_services = services or load_core_classroom_services()
    workspace_status = _workspace_for_assessment(active_services)
    workspace_root = Path(workspace_status.root)

    try:
        school_year_state = active_services.load_school_year_state(workspace_root)
    except Exception as error:
        raise _bounded_core_failure("school-year", error) from error

    classes = _assess_classes(workspace_root, active_services)

    try:
        standards_library = active_services.load_workspace_standards_library(
            workspace_root
        )
    except Exception as error:
        raise _bounded_core_failure("standards-library", error) from error

    try:
        starter_packs = active_services.list_starter_standards_packs()
    except Exception as error:
        raise _bounded_core_failure("starter-standards", error) from error

    active_school_year: str | None = None
    if school_year_state is not None and school_year_state.closed_at is None:
        active_school_year = school_year_state.active_school_year

    academic_period_calendar: AcademicPeriodCalendarLike | None = None
    academic_period_revision: int | None = None
    if active_school_year is not None:
        try:
            academic_period_calendar = (
                active_services.load_current_academic_period_calendar(
                    workspace_root,
                    active_school_year,
                )
            )
            academic_period_revision = (
                active_services.get_current_academic_period_calendar_revision(
                    workspace_root,
                    active_school_year,
                )
            )
        except Exception as error:
            raise _bounded_core_failure("Academic Period calendar", error) from error

        if academic_period_calendar is None and academic_period_revision is not None:
            raise ClassroomSetupAssessmentError(
                "Existing Core Academic Period state is inconsistent: a current "
                "revision exists but no current calendar could be loaded."
            )
        if academic_period_calendar is not None:
            if academic_period_revision is None:
                raise ClassroomSetupAssessmentError(
                    "Existing Core Academic Period state is inconsistent: a current "
                    "calendar exists but its revision could not be resolved."
                )
            if academic_period_calendar.school_year != active_school_year:
                raise ClassroomSetupAssessmentError(
                    "Existing Core Academic Period state is inconsistent: the current "
                    "calendar school year does not match the active school year."
                )
            if academic_period_calendar.calendar_revision != academic_period_revision:
                raise ClassroomSetupAssessmentError(
                    "Existing Core Academic Period state is inconsistent: the current "
                    "calendar and revision pointer disagree."
                )

    return SharedSetupAssessment(
        workspace_root=workspace_root,
        workspace_source=workspace_status.source,
        school_year_state=school_year_state,
        classes=classes,
        standards_library=standards_library,
        starter_standards_packs=tuple(starter_packs),
        academic_period_calendar=academic_period_calendar,
        academic_period_revision=academic_period_revision,
    )


__all__ = (
    "ClassSetupAssessment",
    "ClassroomSetupAssessmentError",
    "ClassroomSetupError",
    "ClassroomWorkspaceError",
    "CoreClassroomServiceError",
    "CoreClassroomServices",
    "SharedSetupAssessment",
    "assess_shared_setup",
    "load_core_classroom_services",
)
