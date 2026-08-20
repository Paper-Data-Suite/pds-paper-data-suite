"""Interactive orchestration for guided shared classroom setup.

Collection and review compose only read-only assessment and in-memory planning
services.  The Core APPLY service bundle is loaded only after exact ``APPLY``;
cancellation and edit paths never acquire setup writers.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from paper_data_suite.classroom_apply import (
    ClassroomSetupPartialSuccessError,
    CoreClassroomApplyServices,
    SetupApplyResult,
    execute_shared_setup_plan,
    load_core_classroom_apply_services,
)
from paper_data_suite.classroom_planning import (
    AcademicPeriodAction,
    AcademicPeriodPlan,
    ClassDisposition,
    ClassPlan,
    ClassroomSetupPlanningError,
    CoreClassroomPlanningServices,
    RosterPlan,
    RosterSourcePlanningError,
    SchoolYearDisposition,
    SchoolYearPlan,
    SharedSetupPlan,
    StandardsPlan,
    assemble_shared_setup_plan,
    load_core_classroom_planning_services,
    plan_academic_periods,
    plan_class,
    plan_roster_import,
    plan_school_year,
    plan_starter_standards,
)
from paper_data_suite.classroom_setup import (
    ClassroomSetupError,
    SharedSetupAssessment,
    assess_shared_setup,
)
from paper_data_suite.workspace_cli import workspace_source_label
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    CoreWorkspaceServiceError,
)

InputReader = Callable[[str], str]
Clock = Callable[[], datetime]


class SetupReviewDecision(str, Enum):
    """Final pre-APPLY decision returned by the review screen."""

    APPLY = "APPLY"
    EDIT = "E"
    CANCEL = "Q"


@dataclass(frozen=True, slots=True)
class SetupCollectionResult:
    """One interactive collection result before final review."""

    plan: SharedSetupPlan | None
    cancelled: bool


def _read(prompt: str, input_fn: InputReader) -> str | None:
    try:
        return input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _join(values: Sequence[str]) -> str:
    items = tuple(values)
    return ", ".join(str(item) for item in items) if items else "none"


def render_initial_setup_assessment(assessment: SharedSetupAssessment) -> str:
    """Render bounded Core-derived state before collecting proposed changes."""
    lines = [
        "Paper Data Suite shared classroom setup",
        "",
        "Workspace:",
        f"  {assessment.workspace_root}",
        "Source:",
        f"  {workspace_source_label(assessment.workspace_source)}",
        "",
        "Current shared state",
        f"  Active school year: {assessment.active_school_year or 'none'}",
        f"  Classes discovered: {len(assessment.classes)}",
    ]
    for item in assessment.classes:
        metadata = "metadata" if item.has_metadata else "no metadata"
        if item.student_count is None:
            roster = "no roster"
        else:
            roster = f"roster with {item.student_count} students"
        lines.append(f"    {item.class_id}: {metadata}; {roster}")
    lines.extend(
        (
            f"  Standards: {assessment.standards_count} definitions; "
            f"{assessment.standards_profile_count} profiles",
            "  Academic Period calendar: "
            + (
                "none for the active school year"
                if assessment.academic_period_calendar is None
                else (
                    f"revision {assessment.academic_period_revision}; "
                    f"{len(assessment.academic_period_calendar.periods)} periods"
                )
            ),
            "",
            "No setup changes have been made.",
        )
    )
    return "\n".join(lines) + "\n"


def render_starter_standards_packs(assessment: SharedSetupAssessment) -> str:
    """Render only Core-advertised starter-pack metadata."""
    lines = ["Available Core starter standards packs"]
    if not assessment.starter_standards_packs:
        lines.append("  none")
        return "\n".join(lines) + "\n"
    for pack in assessment.starter_standards_packs:
        lines.extend(
            (
                f"  {pack.pack_id} — {pack.title}",
                f"    Source: {pack.source}",
                f"    Grade bands: {_join(pack.grade_bands)}",
                f"    Courses: {_join(pack.courses)}",
                f"    Standards: {pack.standard_count}",
                f"    Profiles: {pack.profile_count}",
            )
        )
    return "\n".join(lines) + "\n"


def _school_year_action(disposition: SchoolYearDisposition) -> str:
    return {
        SchoolYearDisposition.NEW: "OPEN",
        SchoolYearDisposition.EXISTING_MATCH: "KEEP",
        SchoolYearDisposition.CONFLICT: "REFUSE",
    }[disposition]


def _class_action(disposition: ClassDisposition) -> str:
    return {
        ClassDisposition.NEW: "CREATE",
        ClassDisposition.EXISTING_MATCH: "KEEP",
        ClassDisposition.CONFLICT: "REFUSE",
    }[disposition]


def render_setup_plan(
    assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
) -> str:
    """Render one bounded final plan without dumping roster rows."""
    lines = [
        "Shared setup review",
        "",
        f"Workspace: {assessment.workspace_root}",
        f"Source: {workspace_source_label(assessment.workspace_source)}",
        "",
        "School year",
        f"  {plan.school_year.requested_school_year}: "
        f"{_school_year_action(plan.school_year.disposition)}",
        f"  {plan.school_year.reason}",
        "",
        "Classes",
    ]
    if not plan.classes:
        lines.append("  No class changes selected.")
    for item in plan.classes:
        lines.append(f"  {item.class_id}: {_class_action(item.disposition)}")
        lines.append(f"    {item.reason}")

    lines.extend(("", "Rosters"))
    roster_by_class = {item.class_id: item for item in plan.rosters}
    if not plan.classes:
        lines.append("  No roster changes selected.")
    for class_plan in plan.classes:
        roster = roster_by_class.get(class_plan.class_id)
        if roster is None:
            existing = class_plan.existing
            if existing is not None and existing.has_roster:
                lines.append(f"  {class_plan.class_id}: KEEP existing roster")
            else:
                lines.append(f"  {class_plan.class_id}: SKIP roster setup")
            continue
        lines.extend(
            (
                f"  {roster.class_id}: {roster.action.value}",
                f"    Incoming students: {roster.incoming_student_count}",
                "    Existing students: "
                + (
                    "none"
                    if roster.existing_student_count is None
                    else str(roster.existing_student_count)
                ),
                f"    New: {roster.new_count}",
                f"    Unchanged: {roster.unchanged_count}",
                f"    Conflicting existing: {roster.conflicting_existing_count}",
                f"    Existing absent from import: {roster.removed_existing_count}",
                f"    {roster.reason}",
            )
        )

    lines.extend(("", "Standards"))
    if plan.standards is None:
        lines.append("  KEEP existing library; no starter pack selected.")
    else:
        standards = plan.standards
        lines.extend(
            (
                f"  Pack {standards.pack_id}: {standards.action.value}",
                f"    Standards to add: {standards.standards_to_add}",
                f"    Standards identical: {standards.standards_identical}",
                f"    Standards conflicts: {len(standards.standard_conflicts)}",
                f"    Profiles to add: {standards.profiles_to_add}",
                f"    Profiles identical: {standards.profiles_identical}",
                f"    Profiles conflicts: {len(standards.profile_conflicts)}",
                f"    {standards.reason}",
            )
        )

    lines.extend(("", "Academic Periods"))
    if plan.academic_periods is None:
        lines.append("  SKIP")
    else:
        periods = plan.academic_periods
        lines.extend(
            (
                f"  {periods.action.value}",
                f"    Period count: {periods.period_count}",
                f"    {periods.reason}",
            )
        )
        if (
            periods.action is AcademicPeriodAction.CREATE
            and periods.candidate_calendar is not None
        ):
            lines.append("    Reviewed period definitions:")
            for period in periods.candidate_calendar.periods:
                parent = getattr(period, "parent_period_id", None) or "none"
                lines.append(
                    "      "
                    f"{getattr(period, 'period_id')} | "
                    f"{getattr(period, 'period_type')} | "
                    f"{getattr(period, 'label')} | "
                    f"{getattr(period, 'start_date')}.."
                    f"{getattr(period, 'end_date')} | "
                    f"parent={parent} | "
                    f"sequence={getattr(period, 'sequence')} | "
                    f"lifecycle={getattr(period, 'lifecycle')}"
                )

    if plan.blocking_reasons:
        lines.extend(("", "APPLY blocked"))
        for reason in plan.blocking_reasons:
            lines.append(f"  - {reason}")
    else:
        lines.extend(("", "Plan is eligible for final APPLY."))
    lines.extend(("", "No setup changes have been made."))
    return "\n".join(lines) + "\n"


def _planning_time(clock: Clock) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ClassroomSetupPlanningError("setup planning clock must be timezone-aware")
    return value


def _collect_school_year(
    assessment: SharedSetupAssessment,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
) -> SchoolYearPlan | None:
    active = assessment.active_school_year
    if active is not None:
        print(f"Using active Core school year: {active}")
        return plan_school_year(assessment, active, services=services)

    while True:
        raw = _read("School year (YYYY-YYYY, Q to cancel): ", input_fn)
        if raw is None or raw.upper() == "Q":
            return None
        if not raw:
            print("Enter an explicit school year or Q to cancel.")
            continue
        try:
            return plan_school_year(assessment, raw, services=services)
        except ClassroomSetupPlanningError as error:
            print(f"School year rejected: {error}")


def _collect_roster(
    assessment: SharedSetupAssessment,
    class_id: str,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
) -> tuple[bool, RosterPlan | None]:
    while True:
        raw = _read(
            f"Roster CSV for {class_id} (Enter to keep/skip, Q to cancel): ",
            input_fn,
        )
        if raw is None or raw.upper() == "Q":
            return False, None
        if not raw:
            return True, None
        try:
            return True, plan_roster_import(
                assessment,
                class_id,
                Path(raw),
                services=services,
            )
        except RosterSourcePlanningError as error:
            print(f"Roster rejected: {error}")
            for diagnostic in error.diagnostics:
                print(f"  {diagnostic}")
        except ClassroomSetupPlanningError as error:
            print(f"Roster rejected: {error}")


def _collect_classes(
    assessment: SharedSetupAssessment,
    school_year: str,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
    planning_time: datetime,
) -> tuple[tuple[ClassPlan, ...], tuple[RosterPlan, ...]] | None:
    classes: list[ClassPlan] = []
    rosters: list[RosterPlan] = []
    seen: set[str] = set()
    print()
    print("Classes")
    print("Enter explicit Core class IDs one at a time. Press Enter when finished.")
    while True:
        raw = _read("Class ID (Enter when done, Q to cancel): ", input_fn)
        if raw is None or raw.upper() == "Q":
            return None
        if not raw:
            return tuple(classes), tuple(rosters)
        if raw in seen:
            print(f"Class {raw!r} is already in this proposed setup.")
            continue
        try:
            class_plan = plan_class(
                assessment,
                raw,
                school_year,
                planning_time=planning_time,
                services=services,
            )
        except ClassroomSetupPlanningError as error:
            print(f"Class rejected: {error}")
            continue
        seen.add(class_plan.class_id)
        classes.append(class_plan)
        print(f"  {class_plan.class_id}: {class_plan.disposition.value}")
        print(f"  {class_plan.reason}")
        if class_plan.blocks_apply:
            continue
        keep_going, roster_plan = _collect_roster(
            assessment,
            class_plan.class_id,
            services,
            input_fn,
        )
        if not keep_going:
            return None
        if roster_plan is not None:
            rosters.append(roster_plan)
            print(f"  Roster action: {roster_plan.action.value}")


def _collect_standards(
    assessment: SharedSetupAssessment,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
) -> tuple[bool, StandardsPlan | None]:
    print()
    print(render_starter_standards_packs(assessment), end="")
    if not assessment.starter_standards_packs:
        return True, None
    while True:
        raw = _read(
            "Starter pack ID (Enter to keep current library, Q to cancel): ",
            input_fn,
        )
        if raw is None or raw.upper() == "Q":
            return False, None
        if not raw:
            return True, None
        try:
            plan = plan_starter_standards(assessment, raw, services=services)
        except ClassroomSetupPlanningError as error:
            print(f"Standards selection rejected: {error}")
            continue
        print(f"Starter pack action: {plan.action.value}")
        return True, plan


def _period_value(
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
) -> tuple[bool, Mapping[str, object] | None]:
    print()
    print("Allowed period types: " + ", ".join(sorted(services.academic_period_types)))
    print(
        "Allowed lifecycle values: "
        + ", ".join(sorted(services.academic_period_lifecycles))
    )
    fields = (
        ("period_id", "Period ID: "),
        ("period_type", "Period type: "),
        ("label", "Label: "),
        ("start_date", "Start date (YYYY-MM-DD): "),
        ("end_date", "End date (YYYY-MM-DD): "),
        ("parent_period_id", "Parent period ID (Enter for none): "),
        ("sequence", "Sequence (positive integer): "),
        ("lifecycle", "Lifecycle: "),
    )
    values: dict[str, object] = {}
    for name, prompt in fields:
        while True:
            raw = _read(prompt, input_fn)
            if raw is None or raw.upper() == "Q":
                return False, None
            if name == "parent_period_id":
                values[name] = raw or None
                break
            if not raw:
                print(f"{name} is required.")
                continue
            if name == "sequence":
                try:
                    values[name] = int(raw)
                except ValueError:
                    print("sequence must be an integer.")
                    continue
                break
            values[name] = raw
            break
    try:
        services.validate_academic_period(values)
    except Exception as error:
        message = str(error)[:500] or error.__class__.__name__
        print(f"Academic Period rejected by Core: {message}")
        return True, None
    return True, values


def _collect_academic_periods(
    assessment: SharedSetupAssessment,
    school_year: str,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader,
    planning_time: datetime,
) -> tuple[bool, AcademicPeriodPlan | None]:
    baseline = plan_academic_periods(
        assessment,
        school_year,
        None,
        planning_time=planning_time,
        services=services,
    )
    if baseline.action is AcademicPeriodAction.KEEP:
        print()
        print(baseline.reason)
        return True, baseline

    while True:
        print()
        print("Academic Period setup")
        print("1. Configure an explicit initial calendar")
        print("2. Skip Academic Period setup")
        print("Q. Cancel")
        choice = _read("Choose an option: ", input_fn)
        if choice is None or choice.upper() == "Q":
            return False, None
        if choice == "2":
            return True, baseline
        if choice != "1":
            print("Choose 1, 2, or Q.")
            continue

        period_values: list[Mapping[str, object]] = []
        while True:
            keep_going, value = _period_value(services, input_fn)
            if not keep_going:
                return False, None
            if value is None:
                print("Re-enter this period with Core-valid values.")
                continue
            period_values.append(value)
            more = _read("Add another period? [y/N, Q to cancel]: ", input_fn)
            if more is None or more.upper() == "Q":
                return False, None
            if more.lower() != "y":
                break
        try:
            plan = plan_academic_periods(
                assessment,
                school_year,
                period_values,
                planning_time=planning_time,
                services=services,
            )
        except ClassroomSetupPlanningError as error:
            print(f"Academic Period calendar rejected: {error}")
            print("Re-enter the complete calendar or choose Skip.")
            continue
        return True, plan


def collect_setup_plan(
    assessment: SharedSetupAssessment,
    *,
    services: CoreClassroomPlanningServices,
    input_fn: InputReader = input,
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> SetupCollectionResult:
    """Collect one complete proposed setup entirely in memory."""
    planning_time = _planning_time(clock)
    school_year = _collect_school_year(assessment, services, input_fn)
    if school_year is None:
        return SetupCollectionResult(plan=None, cancelled=True)

    class_result = _collect_classes(
        assessment,
        school_year.requested_school_year,
        services,
        input_fn,
        planning_time,
    )
    if class_result is None:
        return SetupCollectionResult(plan=None, cancelled=True)
    classes, rosters = class_result

    continue_setup, standards = _collect_standards(assessment, services, input_fn)
    if not continue_setup:
        return SetupCollectionResult(plan=None, cancelled=True)

    continue_setup, academic_periods = _collect_academic_periods(
        assessment,
        school_year.requested_school_year,
        services,
        input_fn,
        planning_time,
    )
    if not continue_setup:
        return SetupCollectionResult(plan=None, cancelled=True)

    plan = assemble_shared_setup_plan(
        school_year,
        classes=classes,
        rosters=rosters,
        standards=standards,
        academic_periods=academic_periods,
    )
    return SetupCollectionResult(plan=plan, cancelled=False)


def review_setup_plan(
    assessment: SharedSetupAssessment,
    plan: SharedSetupPlan,
    *,
    input_fn: InputReader = input,
) -> SetupReviewDecision:
    """Render the final plan and require exact APPLY for write authorization."""
    print()
    print(render_setup_plan(assessment, plan), end="")
    while True:
        print()
        print("APPLY   apply the reviewed plan")
        print("E       edit the plan")
        print("Q       cancel")
        choice = _read("Choose APPLY, E, or Q: ", input_fn)
        if choice is None or choice.upper() == "Q":
            return SetupReviewDecision.CANCEL
        if choice.upper() == "E":
            return SetupReviewDecision.EDIT
        if choice == "APPLY":
            if plan.can_apply:
                return SetupReviewDecision.APPLY
            print("APPLY is blocked until every conflict is resolved.")
            continue
        print("Type exact APPLY, E, or Q.")


def _cancel_shared_setup() -> int:
    print("Shared classroom setup cancelled. No setup changes were made.")
    return 0


def _print_setup_failure(error: Exception) -> None:
    message = str(error)[:800] or error.__class__.__name__
    print(f"Shared classroom setup failed: {message}", file=sys.stderr)


def _render_apply_success(result: SetupApplyResult) -> None:
    print()
    print("Shared classroom setup complete")
    if result.changed_actions:
        print("Core changes applied and verified:")
        for action in result.changed_actions:
            print(f"  {action}")
    else:
        print("No persistent changes were needed; reviewed state was already current.")
    print("Safe reruns are supported; Core remains authoritative for shared state.")


def _render_partial_success(error: ClassroomSetupPartialSuccessError) -> None:
    print("Shared classroom setup stopped after partial success.", file=sys.stderr)
    if error.changed_actions:
        print("Core writes that succeeded before the failure:", file=sys.stderr)
        for action in error.changed_actions:
            print(f"  {action}", file=sys.stderr)
    print(f"Detail: {error}", file=sys.stderr)
    print(
        "No cross-domain rollback was attempted. Rerun 'pds setup' to reassess "
        "the current Core state and continue safely.",
        file=sys.stderr,
    )


def run_classroom_setup(
    input_fn: InputReader = input,
    *,
    clock: Clock = lambda: datetime.now(timezone.utc),
    planning_services: CoreClassroomPlanningServices | None = None,
    apply_services_loader: Callable[[], CoreClassroomApplyServices] = (
        load_core_classroom_apply_services
    ),
) -> int:
    """Run the complete guided shared-classroom setup workflow."""
    try:
        active_planning = (
            planning_services or load_core_classroom_planning_services()
        )
        assessment = assess_shared_setup(services=active_planning.readers)
    except (
        ClassroomSetupError,
        CoreWorkspaceQualificationError,
        CoreWorkspaceServiceError,
    ) as error:
        _print_setup_failure(error)
        return 1

    print(render_initial_setup_assessment(assessment), end="")
    while True:
        try:
            collection = collect_setup_plan(
                assessment,
                services=active_planning,
                input_fn=input_fn,
                clock=clock,
            )
        except ClassroomSetupError as error:
            _print_setup_failure(error)
            return 1
        if collection.cancelled or collection.plan is None:
            return _cancel_shared_setup()

        decision = review_setup_plan(
            assessment,
            collection.plan,
            input_fn=input_fn,
        )
        if decision is SetupReviewDecision.CANCEL:
            return _cancel_shared_setup()
        if decision is SetupReviewDecision.EDIT:
            print("Editing the in-memory plan. No setup changes have been made.")
            continue

        try:
            apply_services = apply_services_loader()
            result = execute_shared_setup_plan(
                assessment,
                collection.plan,
                services=apply_services,
                clock=clock,
            )
        except ClassroomSetupPartialSuccessError as error:
            _render_partial_success(error)
            return 1
        except (
            ClassroomSetupError,
            CoreWorkspaceQualificationError,
            CoreWorkspaceServiceError,
        ) as error:
            _print_setup_failure(error)
            return 1

        _render_apply_success(result)
        return 0


__all__ = (
    "SetupCollectionResult",
    "SetupReviewDecision",
    "collect_setup_plan",
    "render_initial_setup_assessment",
    "render_setup_plan",
    "render_starter_standards_packs",
    "review_setup_plan",
    "run_classroom_setup",
)
