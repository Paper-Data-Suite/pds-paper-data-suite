"""Final APPLY execution for guided shared classroom setup.

The execution layer is loaded only after the teacher has reviewed an in-memory
plan and chosen exact ``APPLY``.  It composes public, suite-qualified PDS Core
writers, performs a fresh read-only preflight before the first mutation, uses
Core overwrite/concurrency protections, verifies each successful step, and
reports partial success without claiming a cross-domain rollback.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.classroom_planning import (
    AcademicPeriodAction,
    ClassDisposition,
    ComparableRosterLike,
    CoreClassroomPlanningServices,
    RosterAction,
    SchoolYearDisposition,
    SharedSetupPlan,
    StandardsAction,
    StarterMergeResultLike,
    load_core_classroom_planning_services,
    plan_starter_standards,
)
from paper_data_suite.classroom_setup import (
    ClassMetadataLike,
    ClassroomSetupError,
    SharedSetupAssessment,
    StandardsLibraryLike,
    assess_shared_setup,
)
from paper_data_suite.compatibility import ReleaseCompatibilityManifest
from paper_data_suite.component_inspection import DistributionVersionLookup

ModuleImporter = Callable[[str], object]
Clock = Callable[[], datetime]


class ClassroomSetupApplyError(ClassroomSetupError):
    """Raised when a reviewed shared setup plan cannot be applied safely."""


class CoreClassroomApplyServiceError(ClassroomSetupApplyError):
    """Raised when a required public Core APPLY service is unavailable."""


class ClassroomSetupPreflightError(ClassroomSetupApplyError):
    """Raised when state changed after review and before the first mutation."""


class ClassroomSetupVerificationError(ClassroomSetupApplyError):
    """Raised when Core state does not match a completed intended action."""


class ClassroomSetupPartialSuccessError(ClassroomSetupApplyError):
    """Raised when a later failure follows one or more successful Core writes."""

    def __init__(
        self,
        message: str,
        *,
        completed_actions: tuple[str, ...],
        changed_actions: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.completed_actions = completed_actions
        self.changed_actions = changed_actions


class SchoolYearOpener(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        school_year: str,
        *,
        opened_at: datetime,
        overwrite: bool = False,
    ) -> object: ...


class ClassMetadataWriter(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        metadata_value: ClassMetadataLike,
        *,
        overwrite: bool = False,
    ) -> Path: ...


class ClassRosterWriter(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        roster: ComparableRosterLike,
        *,
        overwrite: bool = False,
    ) -> Path: ...


class StarterStandardsInstaller(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        pack_id: str,
        existing_library: StandardsLibraryLike,
        *,
        overwrite_conflicts: bool = False,
    ) -> StarterMergeResultLike: ...


class AcademicPeriodCalendarWriter(Protocol):
    def __call__(
        self,
        workspace_root: str | Path,
        calendar: object,
        *,
        expected_current_revision: int | None,
    ) -> Path: ...


@dataclass(frozen=True, slots=True)
class CoreClassroomApplyServices:
    """Exact-qualified public Core services reachable after final APPLY."""

    planning: CoreClassroomPlanningServices
    open_school_year: SchoolYearOpener
    write_class_metadata_for_class: ClassMetadataWriter
    write_class_roster: ClassRosterWriter
    install_starter_standards_library: StarterStandardsInstaller
    write_academic_period_calendar: AcademicPeriodCalendarWriter


@dataclass(frozen=True, slots=True)
class SetupApplyResult:
    """Verified outcome of one complete APPLY attempt."""

    completed_actions: tuple[str, ...]
    changed_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetupPreflight:
    """Fresh Core state validated immediately before the first mutation."""

    assessment: SharedSetupAssessment


def _required_callable(module: object, module_name: str, name: str) -> object:
    value = getattr(module, name, None)
    if not callable(value):
        raise CoreClassroomApplyServiceError(
            "Suite-qualified Core does not expose public callable "
            f"{module_name}.{name}."
        )
    return value


def _import_core_module(module_name: str, module_importer: ModuleImporter) -> object:
    try:
        return module_importer(module_name)
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise CoreClassroomApplyServiceError(
            f"Could not import public Core APPLY services from {module_name}: {message}"
        ) from error


def load_core_classroom_apply_services(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
) -> CoreClassroomApplyServices:
    """Qualify Core exactly, then load only public writers used by APPLY."""
    planning = load_core_classroom_planning_services(
        manifest,
        version_lookup=version_lookup,
        module_importer=module_importer,
    )
    school_years = _import_core_module("pds_core.school_years", module_importer)
    classes = _import_core_module("pds_core.classes", module_importer)
    class_metadata = _import_core_module("pds_core.class_metadata", module_importer)
    starter_standards = _import_core_module(
        "pds_core.starter_standards",
        module_importer,
    )
    academic_period_storage = _import_core_module(
        "pds_core.academic_period_storage",
        module_importer,
    )
    return CoreClassroomApplyServices(
        planning=planning,
        open_school_year=cast(
            SchoolYearOpener,
            _required_callable(
                school_years,
                "pds_core.school_years",
                "open_school_year",
            ),
        ),
        write_class_metadata_for_class=cast(
            ClassMetadataWriter,
            _required_callable(
                class_metadata,
                "pds_core.class_metadata",
                "write_class_metadata_for_class",
            ),
        ),
        write_class_roster=cast(
            ClassRosterWriter,
            _required_callable(
                classes,
                "pds_core.classes",
                "write_class_roster",
            ),
        ),
        install_starter_standards_library=cast(
            StarterStandardsInstaller,
            _required_callable(
                starter_standards,
                "pds_core.starter_standards",
                "install_starter_standards_library",
            ),
        ),
        write_academic_period_calendar=cast(
            AcademicPeriodCalendarWriter,
            _required_callable(
                academic_period_storage,
                "pds_core.academic_period_storage",
                "write_academic_period_calendar",
            ),
        ),
    )


def _metadata_material(value: ClassMetadataLike | None) -> object:
    if value is None:
        return None
    return (
        value.class_id,
        value.school_year,
        dict(value.module_details),
    )


def _student_material(value: object) -> tuple[object, ...]:
    return (
        getattr(value, "class_id"),
        getattr(value, "student_id"),
        getattr(value, "last_name"),
        getattr(value, "first_name"),
        getattr(value, "period"),
        tuple(sorted(cast(Mapping[str, str], getattr(value, "extra_fields")).items())),
    )


def _roster_material(value: ComparableRosterLike | None) -> object:
    if value is None:
        return None
    return (
        value.class_id,
        tuple(value.columns),
        tuple(_student_material(student) for student in value.students),
    )


def _standards_material(value: StandardsLibraryLike) -> tuple[object, ...]:
    return (tuple(value.standards), tuple(value.profiles))


def _school_year_state_material(value: object | None) -> object:
    if value is None:
        return None
    return (
        getattr(value, "active_school_year"),
        getattr(value, "opened_at"),
        getattr(value, "closed_at"),
    )


def _starter_pack_material(value: object) -> tuple[object, ...]:
    return (
        getattr(value, "pack_id"),
        getattr(value, "title"),
        getattr(value, "source"),
        tuple(getattr(value, "grade_bands")),
        tuple(getattr(value, "courses")),
        getattr(value, "standard_count"),
        getattr(value, "profile_count"),
    )


def _calendar_material(value: object | None) -> object:
    if value is None:
        return None
    return (
        getattr(value, "school_year"),
        getattr(value, "calendar_revision"),
        tuple(getattr(value, "periods")),
    )


def _assessment_material(value: SharedSetupAssessment) -> tuple[object, ...]:
    classes = tuple(
        (
            item.class_id,
            _metadata_material(item.metadata),
            _roster_material(cast(ComparableRosterLike | None, item.roster)),
        )
        for item in sorted(value.classes, key=lambda item: item.class_id)
    )
    starters = tuple(
        _starter_pack_material(pack) for pack in value.starter_standards_packs
    )
    return (
        value.workspace_root,
        value.workspace_source,
        _school_year_state_material(value.school_year_state),
        classes,
        _standards_material(value.standards_library),
        starters,
        _calendar_material(value.academic_period_calendar),
        value.academic_period_revision,
    )


def _preflight_period_state(
    assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
    services: CoreClassroomApplyServices,
) -> None:
    period_plan = plan.academic_periods
    if period_plan is None:
        return
    readers = services.planning.readers
    try:
        current = readers.load_current_academic_period_calendar(
            assessment.workspace_root,
            period_plan.school_year,
        )
        revision = readers.get_current_academic_period_calendar_revision(
            assessment.workspace_root,
            period_plan.school_year,
        )
    except Exception as error:
        message = str(error)[:500] or error.__class__.__name__
        raise ClassroomSetupPreflightError(
            "Core could not re-check Academic Period state before APPLY: "
            f"{message}"
        ) from error

    if period_plan.action in {
        AcademicPeriodAction.CREATE,
        AcademicPeriodAction.SKIP,
    }:
        if current is not None or revision is not None:
            raise ClassroomSetupPreflightError(
                "Academic Period state changed after review. Rerun 'pds setup' "
                "before applying changes."
            )
        return
    if period_plan.action is AcademicPeriodAction.KEEP:
        candidate = period_plan.candidate_calendar
        if (
            candidate is None
            or revision != candidate.calendar_revision
            or _calendar_material(current) != _calendar_material(candidate)
        ):
            raise ClassroomSetupPreflightError(
                "The reviewed Academic Period calendar changed before APPLY. "
                "Rerun 'pds setup'."
            )


def _preflight_roster_sources(
    plan: SharedSetupPlan,
    services: CoreClassroomApplyServices,
) -> None:
    for roster_plan in plan.rosters:
        try:
            current_source = services.planning.load_roster(roster_plan.source_path)
        except Exception as error:
            message = str(error)[:500] or error.__class__.__name__
            raise ClassroomSetupPreflightError(
                f"Roster source for {roster_plan.class_id} could not be revalidated: "
                f"{message}"
            ) from error
        if _roster_material(current_source) != _roster_material(
            roster_plan.incoming_roster
        ):
            raise ClassroomSetupPreflightError(
                f"Roster source for {roster_plan.class_id} changed after review. "
                "Rerun 'pds setup' before applying it."
            )


def _preflight_standards(
    assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
    services: CoreClassroomApplyServices,
) -> None:
    standards_plan = plan.standards
    if standards_plan is None:
        return
    try:
        current_plan = plan_starter_standards(
            assessment,
            standards_plan.pack_id,
            services=services.planning,
        )
    except Exception as error:
        message = str(error)[:500] or error.__class__.__name__
        raise ClassroomSetupPreflightError(
            "Selected starter standards could not be revalidated before APPLY: "
            f"{message}"
        ) from error
    if (
        current_plan.action is not standards_plan.action
        or _standards_material(current_plan.candidate_library)
        != _standards_material(standards_plan.candidate_library)
    ):
        raise ClassroomSetupPreflightError(
            "Starter standards merge results changed after review. "
            "Rerun 'pds setup' before applying them."
        )


def preflight_setup_plan(
    reviewed_assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
    *,
    services: CoreClassroomApplyServices,
) -> SetupPreflight:
    """Re-read all reviewed shared state before permitting the first mutation."""
    if not plan.can_apply:
        raise ClassroomSetupPreflightError(
            "The reviewed setup plan still contains a blocking conflict."
        )
    try:
        current = assess_shared_setup(services=services.planning.readers)
    except ClassroomSetupError:
        raise
    except Exception as error:
        message = str(error)[:500] or error.__class__.__name__
        raise ClassroomSetupPreflightError(
            f"Core shared state could not be re-assessed before APPLY: {message}"
        ) from error

    if current.workspace_root != reviewed_assessment.workspace_root:
        raise ClassroomSetupPreflightError(
            "The resolved Core workspace changed after review. Rerun 'pds setup'."
        )
    if _assessment_material(current) != _assessment_material(reviewed_assessment):
        raise ClassroomSetupPreflightError(
            "Core shared state changed after review. No setup mutation was made; "
            "rerun 'pds setup' to review the current state."
        )

    _preflight_roster_sources(plan, services)
    _preflight_standards(current, plan, services)
    _preflight_period_state(current, plan, services)
    return SetupPreflight(assessment=current)


def _apply_time(clock: Clock) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ClassroomSetupApplyError("setup APPLY clock must be timezone-aware")
    return value


def _verify_school_year(
    root: Path,
    school_year: str,
    services: CoreClassroomApplyServices,
) -> None:
    try:
        state = services.planning.readers.load_school_year_state(root)
    except Exception as error:
        raise ClassroomSetupVerificationError(
            f"Could not verify school year after APPLY: {error}"
        ) from error
    if (
        state is None
        or state.closed_at is not None
        or state.active_school_year != school_year
    ):
        raise ClassroomSetupVerificationError(
            f"Core did not report school year {school_year} as open after APPLY."
        )


def _verify_class(
    root: Path,
    class_id: str,
    expected: ClassMetadataLike,
    services: CoreClassroomApplyServices,
) -> None:
    try:
        current = services.planning.readers.load_class_metadata_for_class(
            root,
            class_id,
        )
    except Exception as error:
        raise ClassroomSetupVerificationError(
            f"Could not verify class {class_id} after APPLY: {error}"
        ) from error
    if _metadata_material(current) != _metadata_material(expected):
        raise ClassroomSetupVerificationError(
            f"Core class metadata for {class_id} differs from the reviewed result."
        )


def _verify_roster(
    root: Path,
    expected: ComparableRosterLike,
    services: CoreClassroomApplyServices,
) -> None:
    try:
        current = services.planning.readers.load_class_roster(
            root,
            expected.class_id,
        )
    except Exception as error:
        raise ClassroomSetupVerificationError(
            f"Could not verify roster for {expected.class_id}: {error}"
        ) from error
    if _roster_material(cast(ComparableRosterLike, current)) != _roster_material(
        expected
    ):
        raise ClassroomSetupVerificationError(
            f"Core roster for {expected.class_id} differs from the reviewed import."
        )


def _verify_standards(
    root: Path,
    expected: StandardsLibraryLike,
    services: CoreClassroomApplyServices,
) -> None:
    try:
        current = services.planning.readers.load_workspace_standards_library(root)
    except Exception as error:
        raise ClassroomSetupVerificationError(
            f"Could not verify standards after APPLY: {error}"
        ) from error
    if _standards_material(current) != _standards_material(expected):
        raise ClassroomSetupVerificationError(
            "Core standards library differs from the reviewed merge result."
        )


def _verify_academic_periods(
    root: Path,
    expected: object,
    services: CoreClassroomApplyServices,
) -> None:
    school_year = cast(str, getattr(expected, "school_year"))
    revision = cast(int, getattr(expected, "calendar_revision"))
    readers = services.planning.readers
    try:
        current = readers.load_current_academic_period_calendar(root, school_year)
        current_revision = readers.get_current_academic_period_calendar_revision(
            root,
            school_year,
        )
    except Exception as error:
        raise ClassroomSetupVerificationError(
            f"Could not verify Academic Period calendar after APPLY: {error}"
        ) from error
    if (
        current_revision != revision
        or _calendar_material(current) != _calendar_material(expected)
    ):
        raise ClassroomSetupVerificationError(
            "Core Academic Period current calendar differs from the reviewed result."
        )


def _jit_check_roster_replacement(
    root: Path,
    plan_roster: object,
    services: CoreClassroomApplyServices,
) -> None:
    expected_existing = cast(
        ComparableRosterLike | None,
        getattr(plan_roster, "existing_roster"),
    )
    if expected_existing is None:
        raise ClassroomSetupApplyError(
            "Reviewed roster replacement is missing its existing Core baseline."
        )
    class_id = cast(str, getattr(plan_roster, "class_id"))
    try:
        current = services.planning.readers.load_class_roster(root, class_id)
    except Exception as error:
        raise ClassroomSetupApplyError(
            f"Could not re-check existing roster for {class_id}: {error}"
        ) from error
    if _roster_material(cast(ComparableRosterLike, current)) != _roster_material(
        expected_existing
    ):
        raise ClassroomSetupApplyError(
            f"Roster for {class_id} changed during APPLY; replacement was refused."
        )


def _jit_check_standards(
    root: Path,
    expected: StandardsLibraryLike,
    services: CoreClassroomApplyServices,
) -> StandardsLibraryLike:
    try:
        current = services.planning.readers.load_workspace_standards_library(root)
    except Exception as error:
        raise ClassroomSetupApplyError(
            f"Could not re-check standards immediately before install: {error}"
        ) from error
    if _standards_material(current) != _standards_material(expected):
        raise ClassroomSetupApplyError(
            "Standards library changed during APPLY; starter installation was refused."
        )
    return current


def _execute_after_preflight(
    preflight: SetupPreflight,
    plan: SharedSetupPlan,
    services: CoreClassroomApplyServices,
    *,
    clock: Clock,
) -> SetupApplyResult:
    root = preflight.assessment.workspace_root
    completed: list[str] = []
    changed: list[str] = []

    try:
        school = plan.school_year
        if school.disposition is SchoolYearDisposition.NEW:
            services.open_school_year(
                root,
                school.requested_school_year,
                opened_at=_apply_time(clock),
                overwrite=False,
            )
            changed.append(f"school_year:OPEN:{school.requested_school_year}")
        _verify_school_year(
            root,
            school.requested_school_year,
            services,
        )
        school_action = (
            "OPEN"
            if school.disposition is SchoolYearDisposition.NEW
            else "KEEP"
        )
        completed.append(
            f"school_year:{school_action}:{school.requested_school_year}"
        )

        for class_plan in plan.classes:
            expected_metadata = class_plan.candidate_metadata
            if class_plan.disposition is ClassDisposition.NEW:
                expected_metadata = services.planning.create_class_metadata(
                    class_plan.class_id,
                    class_plan.school_year,
                    created_at=_apply_time(clock),
                    module_details=dict(class_plan.candidate_metadata.module_details),
                )
                services.write_class_metadata_for_class(
                    root,
                    expected_metadata,
                    overwrite=False,
                )
                changed.append(f"class:CREATE:{class_plan.class_id}")
            _verify_class(root, class_plan.class_id, expected_metadata, services)
            action = (
                "CREATE"
                if class_plan.disposition is ClassDisposition.NEW
                else "KEEP"
            )
            completed.append(f"class:{action}:{class_plan.class_id}")

        for roster_plan in plan.rosters:
            if roster_plan.action is RosterAction.CREATE:
                services.write_class_roster(
                    root,
                    roster_plan.incoming_roster,
                    overwrite=False,
                )
                changed.append(f"roster:CREATE:{roster_plan.class_id}")
            elif roster_plan.action is RosterAction.REPLACE:
                _jit_check_roster_replacement(root, roster_plan, services)
                services.write_class_roster(
                    root,
                    roster_plan.incoming_roster,
                    overwrite=True,
                )
                changed.append(f"roster:REPLACE:{roster_plan.class_id}")
            elif roster_plan.action is not RosterAction.KEEP:
                raise ClassroomSetupApplyError(
                    f"Roster action {roster_plan.action.value} is not APPLY-eligible."
                )
            _verify_roster(root, roster_plan.incoming_roster, services)
            completed.append(
                f"roster:{roster_plan.action.value}:{roster_plan.class_id}"
            )

        standards_plan = plan.standards
        if standards_plan is not None:
            if standards_plan.action is StandardsAction.INSTALL:
                baseline = _jit_check_standards(
                    root,
                    preflight.assessment.standards_library,
                    services,
                )
                services.install_starter_standards_library(
                    root,
                    standards_plan.pack_id,
                    baseline,
                    overwrite_conflicts=False,
                )
                changed.append(f"standards:INSTALL:{standards_plan.pack_id}")
            elif standards_plan.action is not StandardsAction.KEEP:
                raise ClassroomSetupApplyError(
                    f"Standards action {standards_plan.action.value} is not "
                    "APPLY-eligible."
                )
            _verify_standards(root, standards_plan.candidate_library, services)
            completed.append(
                f"standards:{standards_plan.action.value}:{standards_plan.pack_id}"
            )

        period_plan = plan.academic_periods
        if period_plan is not None:
            if period_plan.action is AcademicPeriodAction.CREATE:
                candidate = period_plan.candidate_calendar
                if candidate is None:
                    raise ClassroomSetupApplyError(
                        "Reviewed Academic Period creation has no candidate calendar."
                    )
                services.write_academic_period_calendar(
                    root,
                    candidate,
                    expected_current_revision=None,
                )
                changed.append(
                    "academic_periods:CREATE:"
                    f"{period_plan.school_year}:revision-1"
                )
                _verify_academic_periods(root, candidate, services)
            elif period_plan.action is AcademicPeriodAction.KEEP:
                candidate = period_plan.candidate_calendar
                if candidate is None:
                    raise ClassroomSetupApplyError(
                        "Reviewed Academic Period KEEP has no current calendar."
                    )
                _verify_academic_periods(root, candidate, services)
            elif period_plan.action is not AcademicPeriodAction.SKIP:
                raise ClassroomSetupApplyError(
                    f"Academic Period action {period_plan.action.value} is not "
                    "APPLY-eligible."
                )
            completed.append(
                "academic_periods:"
                f"{period_plan.action.value}:{period_plan.school_year}"
            )
    except Exception as error:
        if isinstance(error, ClassroomSetupApplyError):
            if changed:
                raise ClassroomSetupPartialSuccessError(
                    f"{error} Some earlier Core writes succeeded; no rollback was "
                    "attempted. Rerun 'pds setup' to assess the resulting state.",
                    completed_actions=tuple(completed),
                    changed_actions=tuple(changed),
                ) from error
            raise

        message = str(error)[:500] or error.__class__.__name__
        failure = ClassroomSetupApplyError(
            f"Core setup operation failed: {message}"
        )
        if changed:
            raise ClassroomSetupPartialSuccessError(
                f"{failure} Some earlier Core writes succeeded; no rollback was "
                "attempted. Rerun 'pds setup' to assess the resulting state.",
                completed_actions=tuple(completed),
                changed_actions=tuple(changed),
            ) from error
        raise failure from error

    return SetupApplyResult(
        completed_actions=tuple(completed),
        changed_actions=tuple(changed),
    )


def execute_shared_setup_plan(
    reviewed_assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
    *,
    services: CoreClassroomApplyServices | None = None,
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> SetupApplyResult:
    """Apply one exact reviewed plan after a mutation-free fresh preflight."""
    active_services = services or load_core_classroom_apply_services()
    preflight = preflight_setup_plan(
        reviewed_assessment,
        plan,
        services=active_services,
    )
    return _execute_after_preflight(
        preflight,
        plan,
        active_services,
        clock=clock,
    )


__all__ = (
    "ClassroomSetupApplyError",
    "ClassroomSetupPartialSuccessError",
    "ClassroomSetupPreflightError",
    "ClassroomSetupVerificationError",
    "CoreClassroomApplyServiceError",
    "CoreClassroomApplyServices",
    "SetupApplyResult",
    "SetupPreflight",
    "execute_shared_setup_plan",
    "load_core_classroom_apply_services",
    "preflight_setup_plan",
)
