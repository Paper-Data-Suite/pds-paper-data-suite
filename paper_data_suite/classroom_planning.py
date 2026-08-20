"""In-memory proposal planning for guided shared classroom setup.

This module composes public, suite-qualified PDS Core validators, factories, and
readers to produce a reviewable setup plan.  It deliberately exposes no Core
setup writers: persistent mutation belongs to the later APPLY execution layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.classroom_setup import (
    ClassroomSetupError,
    ClassSetupAssessment,
    CoreClassroomServices,
    SharedSetupAssessment,
    StandardsLibraryLike,
    load_core_classroom_services,
)
from paper_data_suite.compatibility import ReleaseCompatibilityManifest
from paper_data_suite.component_inspection import DistributionVersionLookup

ModuleImporter = Callable[[str], object]


class ClassroomSetupPlanningError(ClassroomSetupError):
    """Raised when a proposed shared setup cannot be validated in memory."""


class CoreClassroomPlanningServiceError(ClassroomSetupPlanningError):
    """Raised when a required public Core planning service is unavailable."""


class RosterSourcePlanningError(ClassroomSetupPlanningError):
    """Raised when Core rejects a teacher-selected roster source."""

    def __init__(self, message: str, *, diagnostics: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class SchoolYearDisposition(str, Enum):
    """Guided classification for a proposed school year."""

    NEW = "NEW"
    EXISTING_MATCH = "EXISTING_MATCH"
    CONFLICT = "CONFLICT"


class ClassDisposition(str, Enum):
    """Guided classification for one proposed class."""

    NEW = "NEW"
    EXISTING_MATCH = "EXISTING_MATCH"
    CONFLICT = "CONFLICT"


class RosterAction(str, Enum):
    """Whole-roster action after Core-valid model comparison."""

    CREATE = "CREATE"
    KEEP = "KEEP"
    REPLACE = "REPLACE"
    REFUSE = "REFUSE"


class StandardsAction(str, Enum):
    """Guided action for one explicitly selected Core starter pack."""

    INSTALL = "INSTALL"
    KEEP = "KEEP"
    REFUSE = "REFUSE"


class AcademicPeriodAction(str, Enum):
    """Guided action for initial Academic Period configuration."""

    CREATE = "CREATE"
    KEEP = "KEEP"
    SKIP = "SKIP"
    REFUSE = "REFUSE"


class ClassMetadataLike(Protocol):
    class_id: str
    school_year: str
    module_details: Mapping[str, object]


class ComparableStudentLike(Protocol):
    class_id: str
    student_id: str
    last_name: str
    first_name: str
    period: str
    extra_fields: Mapping[str, str]


class ComparableRosterLike(Protocol):
    class_id: str
    students: Sequence[ComparableStudentLike]
    columns: Sequence[str]
    source_path: Path | None


class StarterMergeResultLike(Protocol):
    pack_id: str
    target_path: Path
    standards_added: int
    standards_skipped: int
    standards_overwritten: int
    profiles_added: int
    profiles_skipped: int
    profiles_overwritten: int
    standard_conflicts: Sequence[str]
    profile_conflicts: Sequence[str]

    @property
    def has_conflicts(self) -> bool: ...

    @property
    def changed_count(self) -> int: ...


class AcademicPeriodCalendarLike(Protocol):
    school_year: str
    calendar_revision: int
    periods: Sequence[object]


class IdentifierValidator(Protocol):
    def __call__(self, value: object, field_name: str = "identifier") -> str: ...


class SchoolYearValidator(Protocol):
    def __call__(self, value: object) -> str: ...


class ClassMetadataFactory(Protocol):
    def __call__(
        self,
        class_id: str,
        school_year: str,
        *,
        created_at: datetime,
        updated_at: datetime | None = None,
        module_details: Mapping[str, object] | None = None,
    ) -> ClassMetadataLike: ...


class RosterLoader(Protocol):
    def __call__(self, path: str | Path) -> ComparableRosterLike: ...


class StandardsLibraryPathGetter(Protocol):
    def __call__(self, workspace_root: str | Path) -> Path: ...


class StarterStandardsLibraryLoader(Protocol):
    def __call__(self, pack_id: str) -> StandardsLibraryLike: ...


class StandardsLibraryMerger(Protocol):
    def __call__(
        self,
        pack_id: str,
        target_path: str | Path,
        existing_library: StandardsLibraryLike,
        starter_library: StandardsLibraryLike,
        *,
        overwrite_conflicts: bool = False,
    ) -> tuple[StandardsLibraryLike, StarterMergeResultLike]: ...


class AcademicPeriodValidator(Protocol):
    def __call__(self, value: object) -> object: ...


class AcademicPeriodCalendarFactory(Protocol):
    def __call__(
        self,
        *,
        schema_version: str,
        record_type: str,
        school_year: str,
        calendar_revision: int,
        created_at: datetime,
        updated_at: datetime,
        periods: Sequence[object],
    ) -> AcademicPeriodCalendarLike: ...


class AcademicPeriodCalendarValidator(Protocol):
    def __call__(self, value: object) -> AcademicPeriodCalendarLike: ...


@dataclass(frozen=True, slots=True)
class CoreClassroomPlanningServices:
    """Qualified public Core services that are safe before final APPLY."""

    readers: CoreClassroomServices
    validate_identifier: IdentifierValidator
    validate_school_year: SchoolYearValidator
    create_class_metadata: ClassMetadataFactory
    load_roster: RosterLoader
    standards_library_path: StandardsLibraryPathGetter
    load_starter_standards_library: StarterStandardsLibraryLoader
    merge_standards_libraries: StandardsLibraryMerger
    validate_academic_period: AcademicPeriodValidator
    academic_period_calendar_factory: AcademicPeriodCalendarFactory
    validate_academic_period_calendar: AcademicPeriodCalendarValidator
    academic_period_calendar_schema_version: str
    academic_period_calendar_record_type: str
    academic_period_types: frozenset[str]
    academic_period_lifecycles: frozenset[str]


@dataclass(frozen=True, slots=True)
class SchoolYearPlan:
    requested_school_year: str
    disposition: SchoolYearDisposition
    reason: str

    @property
    def blocks_apply(self) -> bool:
        return self.disposition is SchoolYearDisposition.CONFLICT


@dataclass(frozen=True, slots=True)
class ClassPlan:
    class_id: str
    school_year: str
    disposition: ClassDisposition
    candidate_metadata: ClassMetadataLike
    existing: ClassSetupAssessment | None
    reason: str

    @property
    def blocks_apply(self) -> bool:
        return self.disposition is ClassDisposition.CONFLICT


@dataclass(frozen=True, slots=True)
class RosterPlan:
    class_id: str
    source_path: Path
    incoming_roster: ComparableRosterLike
    existing_roster: ComparableRosterLike | None
    action: RosterAction
    incoming_student_count: int
    existing_student_count: int | None
    new_count: int
    unchanged_count: int
    conflicting_existing_count: int
    removed_existing_count: int
    reason: str

    @property
    def blocks_apply(self) -> bool:
        return self.action is RosterAction.REFUSE


@dataclass(frozen=True, slots=True)
class StandardsPlan:
    pack_id: str
    action: StandardsAction
    candidate_library: StandardsLibraryLike
    target_path: Path
    standards_to_add: int
    standards_identical: int
    standard_conflicts: tuple[str, ...]
    profiles_to_add: int
    profiles_identical: int
    profile_conflicts: tuple[str, ...]
    reason: str

    @property
    def blocks_apply(self) -> bool:
        return self.action is StandardsAction.REFUSE


@dataclass(frozen=True, slots=True)
class AcademicPeriodPlan:
    school_year: str
    action: AcademicPeriodAction
    candidate_calendar: AcademicPeriodCalendarLike | None
    period_count: int
    reason: str

    @property
    def blocks_apply(self) -> bool:
        return self.action is AcademicPeriodAction.REFUSE


@dataclass(frozen=True, slots=True)
class SharedSetupPlan:
    """One complete, in-memory, reviewable proposal before APPLY."""

    school_year: SchoolYearPlan
    classes: tuple[ClassPlan, ...]
    rosters: tuple[RosterPlan, ...]
    standards: StandardsPlan | None
    academic_periods: AcademicPeriodPlan | None

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.school_year.blocks_apply:
            reasons.append(self.school_year.reason)
        reasons.extend(plan.reason for plan in self.classes if plan.blocks_apply)
        reasons.extend(plan.reason for plan in self.rosters if plan.blocks_apply)
        if self.standards is not None and self.standards.blocks_apply:
            reasons.append(self.standards.reason)
        if self.academic_periods is not None and self.academic_periods.blocks_apply:
            reasons.append(self.academic_periods.reason)
        return tuple(reasons)

    @property
    def can_apply(self) -> bool:
        return not self.blocking_reasons


def _required_callable(module: object, module_name: str, name: str) -> object:
    value = getattr(module, name, None)
    if not callable(value):
        raise CoreClassroomPlanningServiceError(
            "Suite-qualified Core does not expose public callable "
            f"{module_name}.{name}."
        )
    return value


def _required_text(module: object, module_name: str, name: str) -> str:
    value = getattr(module, name, None)
    if not isinstance(value, str) or not value:
        raise CoreClassroomPlanningServiceError(
            "Suite-qualified Core does not expose public text contract "
            f"{module_name}.{name}."
        )
    return value


def _required_text_set(module: object, module_name: str, name: str) -> frozenset[str]:
    value = getattr(module, name, None)
    if not isinstance(value, (set, frozenset)) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise CoreClassroomPlanningServiceError(
            "Suite-qualified Core does not expose public text-set contract "
            f"{module_name}.{name}."
        )
    return frozenset(value)


def _import_core_module(module_name: str, module_importer: ModuleImporter) -> object:
    try:
        return module_importer(module_name)
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreClassroomPlanningServiceError(
            "Could not import public Core planning services from "
            f"{module_name}: {message}"
        ) from error


def load_core_classroom_planning_services(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
) -> CoreClassroomPlanningServices:
    """Qualify Core exactly, then load public pre-APPLY planning contracts."""
    readers = load_core_classroom_services(
        manifest,
        version_lookup=version_lookup,
        module_importer=module_importer,
    )

    identifiers = _import_core_module("pds_core.identifiers", module_importer)
    school_years = _import_core_module("pds_core.school_years", module_importer)
    class_metadata = _import_core_module("pds_core.class_metadata", module_importer)
    rosters = _import_core_module("pds_core.rosters", module_importer)
    standards = _import_core_module("pds_core.standards", module_importer)
    starter_standards = _import_core_module(
        "pds_core.starter_standards",
        module_importer,
    )
    academic_periods = _import_core_module("pds_core.academic_periods", module_importer)

    return CoreClassroomPlanningServices(
        readers=readers,
        validate_identifier=cast(
            IdentifierValidator,
            _required_callable(
                identifiers,
                "pds_core.identifiers",
                "validate_identifier",
            ),
        ),
        validate_school_year=cast(
            SchoolYearValidator,
            _required_callable(
                school_years,
                "pds_core.school_years",
                "validate_school_year",
            ),
        ),
        create_class_metadata=cast(
            ClassMetadataFactory,
            _required_callable(
                class_metadata,
                "pds_core.class_metadata",
                "create_class_metadata",
            ),
        ),
        load_roster=cast(
            RosterLoader,
            _required_callable(rosters, "pds_core.rosters", "load_roster"),
        ),
        standards_library_path=cast(
            StandardsLibraryPathGetter,
            _required_callable(
                standards,
                "pds_core.standards",
                "standards_library_path",
            ),
        ),
        load_starter_standards_library=cast(
            StarterStandardsLibraryLoader,
            _required_callable(
                starter_standards,
                "pds_core.starter_standards",
                "load_starter_standards_library",
            ),
        ),
        merge_standards_libraries=cast(
            StandardsLibraryMerger,
            _required_callable(
                starter_standards,
                "pds_core.starter_standards",
                "merge_standards_libraries",
            ),
        ),
        validate_academic_period=cast(
            AcademicPeriodValidator,
            _required_callable(
                academic_periods,
                "pds_core.academic_periods",
                "validate_academic_period",
            ),
        ),
        academic_period_calendar_factory=cast(
            AcademicPeriodCalendarFactory,
            _required_callable(
                academic_periods,
                "pds_core.academic_periods",
                "AcademicPeriodCalendar",
            ),
        ),
        validate_academic_period_calendar=cast(
            AcademicPeriodCalendarValidator,
            _required_callable(
                academic_periods,
                "pds_core.academic_periods",
                "validate_academic_period_calendar",
            ),
        ),
        academic_period_calendar_schema_version=_required_text(
            academic_periods,
            "pds_core.academic_periods",
            "ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION",
        ),
        academic_period_calendar_record_type=_required_text(
            academic_periods,
            "pds_core.academic_periods",
            "ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE",
        ),
        academic_period_types=_required_text_set(
            academic_periods,
            "pds_core.academic_periods",
            "ACADEMIC_PERIOD_TYPES",
        ),
        academic_period_lifecycles=_required_text_set(
            academic_periods,
            "pds_core.academic_periods",
            "ACADEMIC_PERIOD_LIFECYCLES",
        ),
    )


def _planning_failure(area: str, error: Exception) -> ClassroomSetupPlanningError:
    message = str(error)[:500] or error.__class__.__name__
    return ClassroomSetupPlanningError(
        f"Core rejected the proposed {area}: {message}"
    )


def plan_school_year(
    assessment: SharedSetupAssessment,
    requested_school_year: str,
    *,
    services: CoreClassroomPlanningServices,
) -> SchoolYearPlan:
    """Validate and classify one explicitly requested school year through Core."""
    try:
        validated = services.validate_school_year(requested_school_year)
    except Exception as error:
        raise _planning_failure("school year", error) from error

    active = assessment.active_school_year
    if active is None:
        return SchoolYearPlan(
            requested_school_year=validated,
            disposition=SchoolYearDisposition.NEW,
            reason=f"No school year is currently open; {validated} can be opened.",
        )
    if active == validated:
        return SchoolYearPlan(
            requested_school_year=validated,
            disposition=SchoolYearDisposition.EXISTING_MATCH,
            reason=f"School year {validated} is already open.",
        )
    return SchoolYearPlan(
        requested_school_year=validated,
        disposition=SchoolYearDisposition.CONFLICT,
        reason=(
            f"School year {active} is already open; guided setup will not replace "
            f"it with {validated}. Resolve the lifecycle state through Core first."
        ),
    )


def _assessment_class(
    assessment: SharedSetupAssessment,
    class_id: str,
) -> ClassSetupAssessment | None:
    return next(
        (item for item in assessment.classes if item.class_id == class_id),
        None,
    )


def plan_class(
    assessment: SharedSetupAssessment,
    class_id: str,
    school_year: str,
    *,
    planning_time: datetime,
    services: CoreClassroomPlanningServices,
) -> ClassPlan:
    """Validate and classify one explicit class proposal through Core."""
    try:
        validated_class_id = services.validate_identifier(class_id, "class_id")
        validated_school_year = services.validate_school_year(school_year)
        candidate = services.create_class_metadata(
            validated_class_id,
            validated_school_year,
            created_at=planning_time,
            module_details={},
        )
    except Exception as error:
        raise _planning_failure("class", error) from error

    existing = _assessment_class(assessment, validated_class_id)
    if existing is None:
        return ClassPlan(
            class_id=validated_class_id,
            school_year=validated_school_year,
            disposition=ClassDisposition.NEW,
            candidate_metadata=candidate,
            existing=None,
            reason="No existing Core class folder or metadata was discovered.",
        )

    metadata_value = existing.metadata
    if metadata_value is None:
        if existing.roster is not None:
            return ClassPlan(
                class_id=validated_class_id,
                school_year=validated_school_year,
                disposition=ClassDisposition.CONFLICT,
                candidate_metadata=candidate,
                existing=existing,
                reason=(
                    f"Class {validated_class_id} has a roster but no valid class "
                    "metadata; guided setup will not guess its school year."
                ),
            )
        return ClassPlan(
            class_id=validated_class_id,
            school_year=validated_school_year,
            disposition=ClassDisposition.NEW,
            candidate_metadata=candidate,
            existing=existing,
            reason=(
                f"Class folder {validated_class_id} exists without metadata or a "
                "roster; guided setup can finish this unambiguous class setup."
            ),
        )

    if (
        metadata_value.class_id == validated_class_id
        and metadata_value.school_year == validated_school_year
    ):
        return ClassPlan(
            class_id=validated_class_id,
            school_year=validated_school_year,
            disposition=ClassDisposition.EXISTING_MATCH,
            candidate_metadata=metadata_value,
            existing=existing,
            reason=(
                f"Class {validated_class_id} already has matching Core metadata for "
                f"{validated_school_year}."
            ),
        )

    return ClassPlan(
        class_id=validated_class_id,
        school_year=validated_school_year,
        disposition=ClassDisposition.CONFLICT,
        candidate_metadata=candidate,
        existing=existing,
        reason=(
            f"Class {validated_class_id} has existing Core metadata for school year "
            f"{metadata_value.school_year}; guided setup will not overwrite it."
        ),
    )


_ROSTER_DIAGNOSTIC_MESSAGES = {
    "invalid_header": "A roster header is invalid.",
    "blank_header": "A roster header must not be blank.",
    "duplicate_header": "A roster header appears more than once.",
    "missing_required_column": "A required roster column is missing.",
    "missing_required_field": "A required roster field is missing.",
    "non_string_value": "A roster field must contain text.",
    "blank_required_value": "A required roster field must not be blank.",
    "invalid_class_id": "A class_id is not a valid Core identifier.",
    "inconsistent_class_id": "The roster contains more than one class_id.",
    "invalid_student_id": "A student_id is not a valid Core identifier.",
    "duplicate_student_id": "A student_id appears more than once.",
    "empty_roster": "The roster contains no valid student rows.",
    "missing_header": "The roster CSV is missing its header row.",
    "malformed_row": "A roster CSV row does not match the header shape.",
}


def _roster_diagnostics(error: Exception) -> tuple[str, ...]:
    """Render bounded structured Core diagnostics without echoing row values."""
    issues = getattr(error, "issues", ())
    try:
        materialized = tuple(issues)
    except TypeError:
        return ()

    diagnostics: list[str] = []
    for issue in materialized[:5]:
        code = getattr(issue, "code", None)
        row_number = getattr(issue, "row_number", None)
        column = getattr(issue, "column", None)
        location: list[str] = []
        if isinstance(row_number, int):
            location.append(f"row {row_number}")
        if isinstance(column, str) and column:
            location.append(f"column {column}")
        prefix = f"{' / '.join(location)}: " if location else ""
        message = (
            _ROSTER_DIAGNOSTIC_MESSAGES.get(
                code,
                "Core rejected this roster entry.",
            )
            if isinstance(code, str)
            else "Core rejected this roster entry."
        )
        diagnostics.append(prefix + message)
    return tuple(diagnostics)


def _student_material(student: ComparableStudentLike) -> tuple[object, ...]:
    return (
        student.class_id,
        student.student_id,
        student.last_name,
        student.first_name,
        student.period,
        tuple(sorted(student.extra_fields.items())),
    )


def _roster_material(roster: ComparableRosterLike) -> tuple[object, ...]:
    return (
        roster.class_id,
        tuple(roster.columns),
        tuple(_student_material(student) for student in roster.students),
    )


def plan_roster_import(
    assessment: SharedSetupAssessment,
    class_id: str,
    source_path: str | Path,
    *,
    services: CoreClassroomPlanningServices,
) -> RosterPlan:
    """Load a roster through Core and classify a whole-roster setup action."""
    try:
        validated_class_id = services.validate_identifier(class_id, "class_id")
    except Exception as error:
        raise _planning_failure("roster target class", error) from error

    source = Path(source_path)
    try:
        incoming = services.load_roster(source)
    except Exception as error:
        diagnostics = _roster_diagnostics(error)
        if diagnostics:
            message = f"Core rejected roster source {source}."
        else:
            detail = str(error)[:300] or error.__class__.__name__
            message = f"Core could not load roster source {source}: {detail}"
        raise RosterSourcePlanningError(
            message,
            diagnostics=diagnostics,
        ) from error

    existing_assessment = _assessment_class(assessment, validated_class_id)
    existing = (
        None
        if existing_assessment is None
        else cast(ComparableRosterLike | None, existing_assessment.roster)
    )

    incoming_count = len(incoming.students)
    existing_count = None if existing is None else len(existing.students)

    if incoming.class_id != validated_class_id:
        return RosterPlan(
            class_id=validated_class_id,
            source_path=source,
            incoming_roster=incoming,
            existing_roster=existing,
            action=RosterAction.REFUSE,
            incoming_student_count=incoming_count,
            existing_student_count=existing_count,
            new_count=0,
            unchanged_count=0,
            conflicting_existing_count=0,
            removed_existing_count=0,
            reason=(
                f"Roster source belongs to class {incoming.class_id}, not explicitly "
                f"selected class {validated_class_id}."
            ),
        )

    if existing is None:
        return RosterPlan(
            class_id=validated_class_id,
            source_path=source,
            incoming_roster=incoming,
            existing_roster=None,
            action=RosterAction.CREATE,
            incoming_student_count=incoming_count,
            existing_student_count=None,
            new_count=incoming_count,
            unchanged_count=0,
            conflicting_existing_count=0,
            removed_existing_count=0,
            reason=f"Class {validated_class_id} has no existing Core roster.",
        )

    existing_by_id = {student.student_id: student for student in existing.students}
    incoming_ids = {student.student_id for student in incoming.students}
    new_count = 0
    unchanged_count = 0
    conflicting_count = 0
    for student in incoming.students:
        current = existing_by_id.get(student.student_id)
        if current is None:
            new_count += 1
        elif _student_material(current) == _student_material(student):
            unchanged_count += 1
        else:
            conflicting_count += 1
    removed_count = sum(
        1 for student in existing.students if student.student_id not in incoming_ids
    )

    if _roster_material(existing) == _roster_material(incoming):
        action = RosterAction.KEEP
        reason = f"Imported roster for {validated_class_id} is materially identical."
    else:
        action = RosterAction.REPLACE
        reason = (
            f"Imported roster for {validated_class_id} differs from the existing "
            "Core roster and therefore requires whole-roster replacement."
        )

    return RosterPlan(
        class_id=validated_class_id,
        source_path=source,
        incoming_roster=incoming,
        existing_roster=existing,
        action=action,
        incoming_student_count=incoming_count,
        existing_student_count=len(existing.students),
        new_count=new_count,
        unchanged_count=unchanged_count,
        conflicting_existing_count=conflicting_count,
        removed_existing_count=removed_count,
        reason=reason,
    )


def plan_starter_standards(
    assessment: SharedSetupAssessment,
    pack_id: str,
    *,
    services: CoreClassroomPlanningServices,
) -> StandardsPlan:
    """Dry-merge one explicitly selected Core starter standards pack."""
    available = {pack.pack_id for pack in assessment.starter_standards_packs}
    if pack_id not in available:
        raise ClassroomSetupPlanningError(
            f"Starter standards pack {pack_id!r} is not advertised by qualified Core."
        )

    try:
        starter = services.load_starter_standards_library(pack_id)
        target = services.standards_library_path(assessment.workspace_root)
        candidate, result = services.merge_standards_libraries(
            pack_id,
            target,
            assessment.standards_library,
            starter,
            overwrite_conflicts=False,
        )
    except Exception as error:
        raise _planning_failure("starter standards selection", error) from error

    standard_conflicts = tuple(result.standard_conflicts)
    profile_conflicts = tuple(result.profile_conflicts)
    if standard_conflicts or profile_conflicts:
        action = StandardsAction.REFUSE
        reason = (
            f"Starter standards pack {pack_id} conflicts with protected existing "
            "standards or profiles; guided setup will not overwrite them."
        )
    elif result.changed_count == 0:
        action = StandardsAction.KEEP
        reason = f"Starter standards pack {pack_id} is already fully present."
    else:
        action = StandardsAction.INSTALL
        reason = f"Starter standards pack {pack_id} can be merged without conflicts."

    return StandardsPlan(
        pack_id=pack_id,
        action=action,
        candidate_library=candidate,
        target_path=Path(result.target_path),
        standards_to_add=result.standards_added,
        standards_identical=result.standards_skipped,
        standard_conflicts=standard_conflicts,
        profiles_to_add=result.profiles_added,
        profiles_identical=result.profiles_skipped,
        profile_conflicts=profile_conflicts,
        reason=reason,
    )


def plan_academic_periods(
    assessment: SharedSetupAssessment,
    school_year: str,
    period_values: Sequence[Mapping[str, object]] | None,
    *,
    planning_time: datetime,
    services: CoreClassroomPlanningServices,
) -> AcademicPeriodPlan:
    """Validate an explicit initial calendar proposal, or represent an explicit skip."""
    try:
        validated_school_year = services.validate_school_year(school_year)
    except Exception as error:
        raise _planning_failure("Academic Period school year", error) from error

    existing = assessment.academic_period_calendar
    existing_revision = assessment.academic_period_revision
    if existing is None or existing.school_year != validated_school_year:
        try:
            existing = services.readers.load_current_academic_period_calendar(
                assessment.workspace_root,
                validated_school_year,
            )
            existing_revision = (
                services.readers.get_current_academic_period_calendar_revision(
                    assessment.workspace_root,
                    validated_school_year,
                )
            )
        except Exception as error:
            raise _planning_failure(
                "existing Academic Period calendar", error
            ) from error

    if existing is None and existing_revision is not None:
        raise ClassroomSetupPlanningError(
            "Core reports an Academic Period revision but no current calendar for "
            f"{validated_school_year}."
        )
    if existing is not None:
        if existing_revision is None:
            raise ClassroomSetupPlanningError(
                "Core reports a current Academic Period calendar without a current "
                f"revision for {validated_school_year}."
            )
        if existing.school_year != validated_school_year:
            raise ClassroomSetupPlanningError(
                "Core returned an Academic Period calendar for the wrong school year."
            )
        if existing.calendar_revision != existing_revision:
            raise ClassroomSetupPlanningError(
                "Core Academic Period calendar and current revision pointer disagree."
            )
        if period_values is not None:
            return AcademicPeriodPlan(
                school_year=validated_school_year,
                action=AcademicPeriodAction.REFUSE,
                candidate_calendar=None,
                period_count=len(existing.periods),
                reason=(
                    f"Academic Period calendar for {validated_school_year} already "
                    "exists; guided setup does not revise existing calendars."
                ),
            )
        return AcademicPeriodPlan(
            school_year=validated_school_year,
            action=AcademicPeriodAction.KEEP,
            candidate_calendar=existing,
            period_count=len(existing.periods),
            reason=(
                f"Academic Period calendar for {validated_school_year} is already "
                "configured and will be kept unchanged."
            ),
        )

    if period_values is None:
        return AcademicPeriodPlan(
            school_year=validated_school_year,
            action=AcademicPeriodAction.SKIP,
            candidate_calendar=None,
            period_count=0,
            reason="Academic Period setup was explicitly skipped.",
        )

    try:
        periods = tuple(
            services.validate_academic_period(period_value)
            for period_value in period_values
        )
        candidate = services.academic_period_calendar_factory(
            schema_version=services.academic_period_calendar_schema_version,
            record_type=services.academic_period_calendar_record_type,
            school_year=validated_school_year,
            calendar_revision=1,
            created_at=planning_time,
            updated_at=planning_time,
            periods=periods,
        )
        validated = services.validate_academic_period_calendar(candidate)
    except Exception as error:
        raise _planning_failure("Academic Period calendar", error) from error

    return AcademicPeriodPlan(
        school_year=validated_school_year,
        action=AcademicPeriodAction.CREATE,
        candidate_calendar=validated,
        period_count=len(validated.periods),
        reason=(
            f"Initial Academic Period calendar revision 1 for {validated_school_year} "
            "is valid in memory."
        ),
    )


def assemble_shared_setup_plan(
    school_year: SchoolYearPlan,
    *,
    classes: Sequence[ClassPlan] = (),
    rosters: Sequence[RosterPlan] = (),
    standards: StandardsPlan | None = None,
    academic_periods: AcademicPeriodPlan | None = None,
) -> SharedSetupPlan:
    """Assemble domain plans and reject internally inconsistent proposal wiring."""
    class_plans = tuple(classes)
    roster_plans = tuple(rosters)

    class_ids = [plan.class_id for plan in class_plans]
    if len(class_ids) != len(set(class_ids)):
        raise ClassroomSetupPlanningError(
            "A shared setup plan cannot contain the same class_id more than once."
        )
    roster_ids = [plan.class_id for plan in roster_plans]
    if len(roster_ids) != len(set(roster_ids)):
        raise ClassroomSetupPlanningError(
            "A shared setup plan cannot contain more than one roster import per class."
        )

    requested_year = school_year.requested_school_year
    for class_plan in class_plans:
        if class_plan.school_year != requested_year:
            raise ClassroomSetupPlanningError(
                f"Class {class_plan.class_id} targets {class_plan.school_year}, not "
                f"selected school year {requested_year}."
            )
    known_class_ids = set(class_ids)
    for roster_plan in roster_plans:
        if roster_plan.class_id not in known_class_ids:
            raise ClassroomSetupPlanningError(
                f"Roster for {roster_plan.class_id} has no corresponding class plan."
            )
    if academic_periods is not None and academic_periods.school_year != requested_year:
        raise ClassroomSetupPlanningError(
            "Academic Period proposal does not target the selected school year."
        )

    return SharedSetupPlan(
        school_year=school_year,
        classes=class_plans,
        rosters=roster_plans,
        standards=standards,
        academic_periods=academic_periods,
    )


__all__ = (
    "AcademicPeriodAction",
    "AcademicPeriodPlan",
    "ClassDisposition",
    "ClassPlan",
    "ClassroomSetupPlanningError",
    "CoreClassroomPlanningServiceError",
    "CoreClassroomPlanningServices",
    "RosterAction",
    "RosterPlan",
    "RosterSourcePlanningError",
    "SchoolYearDisposition",
    "SchoolYearPlan",
    "SharedSetupPlan",
    "StandardsAction",
    "StandardsPlan",
    "assemble_shared_setup_plan",
    "load_core_classroom_planning_services",
    "plan_academic_periods",
    "plan_class",
    "plan_roster_import",
    "plan_school_year",
    "plan_starter_standards",
)
