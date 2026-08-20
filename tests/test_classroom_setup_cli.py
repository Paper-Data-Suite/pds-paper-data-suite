from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import paper_data_suite.classroom_setup_cli as setup_cli
from paper_data_suite.classroom_planning import (
    AcademicPeriodAction,
    AcademicPeriodPlan,
    ClassDisposition,
    ClassPlan,
    CoreClassroomPlanningServices,
    RosterAction,
    RosterPlan,
    SchoolYearDisposition,
    SchoolYearPlan,
    SharedSetupPlan,
    StandardsAction,
    StandardsPlan,
)
from paper_data_suite.classroom_setup import (
    ClassSetupAssessment,
    SharedSetupAssessment,
)


@dataclass(frozen=True)
class FakeState:
    active_school_year: str
    opened_at: datetime
    closed_at: datetime | None = None


@dataclass(frozen=True)
class FakeLibrary:
    standards: tuple[object, ...] = ()
    profiles: tuple[object, ...] = ()


@dataclass(frozen=True)
class FakePack:
    pack_id: str = "starter"
    title: str = "Synthetic standards"
    source: str = "Core synthetic fixture"
    grade_bands: tuple[str, ...] = ("9-10",)
    courses: tuple[str, ...] = ("English",)
    standard_count: int = 3
    profile_count: int = 1


@dataclass(frozen=True)
class FakeMetadata:
    class_id: str
    school_year: str
    module_details: dict[str, object]


@dataclass(frozen=True)
class FakeStudent:
    class_id: str
    student_id: str
    last_name: str
    first_name: str
    period: str
    extra_fields: dict[str, str]


@dataclass(frozen=True)
class FakeRoster:
    class_id: str
    students: tuple[FakeStudent, ...]
    columns: tuple[str, ...]
    source_path: Path | None = None


@dataclass(frozen=True)
class FakeCalendar:
    school_year: str
    calendar_revision: int
    periods: tuple[object, ...]


@dataclass(frozen=True)
class FakePeriod:
    period_id: str
    period_type: str
    label: str
    start_date: str
    end_date: str
    parent_period_id: str | None
    sequence: int
    lifecycle: str


def fake_assessment(
    tmp_path: Path,
    *,
    active_year: str | None = None,
    classes: tuple[ClassSetupAssessment, ...] = (),
    calendar: FakeCalendar | None = None,
) -> SharedSetupAssessment:
    state = None
    if active_year is not None:
        state = FakeState(
            active_school_year=active_year,
            opened_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
    return SharedSetupAssessment(
        workspace_root=tmp_path,
        workspace_source="saved_config",
        school_year_state=state,
        classes=classes,
        standards_library=FakeLibrary((object(), object()), (object(),)),
        starter_standards_packs=(FakePack(),),
        academic_period_calendar=calendar,
        academic_period_revision=(
            None if calendar is None else calendar.calendar_revision
        ),
    )


def fake_services() -> CoreClassroomPlanningServices:
    return cast(
        CoreClassroomPlanningServices,
        SimpleNamespace(
            academic_period_types=frozenset({"quarter", "semester"}),
            academic_period_lifecycles=frozenset(
                {"planned", "active", "closed", "cancelled"}
            ),
            validate_academic_period=lambda value: value,
        ),
    )


def input_reader(values: list[str]):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def school_plan(
    year: str = "2026-2027",
    disposition: SchoolYearDisposition = SchoolYearDisposition.NEW,
) -> SchoolYearPlan:
    return SchoolYearPlan(year, disposition, "school year reason")


def class_plan(
    assessment: SharedSetupAssessment,
    *,
    disposition: ClassDisposition = ClassDisposition.NEW,
) -> ClassPlan:
    existing = next(
        (item for item in assessment.classes if item.class_id == "eng10"),
        None,
    )
    return ClassPlan(
        class_id="eng10",
        school_year="2026-2027",
        disposition=disposition,
        candidate_metadata=FakeMetadata("eng10", "2026-2027", {}),
        existing=existing,
        reason="class reason",
    )


def test_initial_assessment_is_bounded_and_does_not_dump_roster(
    tmp_path: Path,
) -> None:
    roster = FakeRoster(
        class_id="eng10",
        students=(
            FakeStudent(
                "eng10",
                "secret-student-id",
                "SensitiveLast",
                "SensitiveFirst",
                "2",
                {},
            ),
        ),
        columns=("class_id", "student_id", "last_name", "first_name", "period"),
    )
    current = fake_assessment(
        tmp_path,
        active_year="2026-2027",
        classes=(
            ClassSetupAssessment(
                "eng10",
                FakeMetadata("eng10", "2026-2027", {}),
                roster,
            ),
        ),
    )

    rendered = setup_cli.render_initial_setup_assessment(current)

    assert str(tmp_path) in rendered
    assert "saved workspace selection" in rendered
    assert "eng10: metadata; roster with 1 students" in rendered
    assert "secret-student-id" not in rendered
    assert "SensitiveFirst" not in rendered
    assert "SensitiveLast" not in rendered


def test_starter_pack_rendering_uses_only_core_metadata(tmp_path: Path) -> None:
    rendered = setup_cli.render_starter_standards_packs(fake_assessment(tmp_path))

    assert "starter — Synthetic standards" in rendered
    assert "Core synthetic fixture" in rendered
    assert "Grade bands: 9-10" in rendered
    assert "Courses: English" in rendered
    assert "Standards: 3" in rendered
    assert "Profiles: 1" in rendered


def test_final_review_shows_whole_roster_counts_without_rows(tmp_path: Path) -> None:
    current = fake_assessment(tmp_path)
    incoming = FakeRoster(
        "eng10",
        (
            FakeStudent("eng10", "s1", "One", "Student", "2", {}),
            FakeStudent("eng10", "s2", "Two", "Student", "2", {}),
        ),
        ("class_id", "student_id", "last_name", "first_name", "period"),
        Path("teacher-private-roster.csv"),
    )
    roster_plan = RosterPlan(
        class_id="eng10",
        source_path=Path("teacher-private-roster.csv"),
        incoming_roster=incoming,
        existing_roster=None,
        action=RosterAction.REPLACE,
        incoming_student_count=2,
        existing_student_count=2,
        new_count=1,
        unchanged_count=0,
        conflicting_existing_count=1,
        removed_existing_count=1,
        reason="whole-roster replacement required",
    )
    standards = StandardsPlan(
        pack_id="starter",
        action=StandardsAction.INSTALL,
        candidate_library=FakeLibrary(),
        target_path=tmp_path / "standards" / "library.json",
        standards_to_add=3,
        standards_identical=1,
        standard_conflicts=(),
        profiles_to_add=1,
        profiles_identical=0,
        profile_conflicts=(),
        reason="standards reason",
    )
    periods = AcademicPeriodPlan(
        "2026-2027",
        AcademicPeriodAction.CREATE,
        FakeCalendar(
            "2026-2027",
            1,
            (
                FakePeriod(
                    "q1",
                    "quarter",
                    "Quarter 1",
                    "2026-09-01",
                    "2026-11-01",
                    None,
                    1,
                    "planned",
                ),
                FakePeriod(
                    "q2",
                    "quarter",
                    "Quarter 2",
                    "2026-11-02",
                    "2027-01-31",
                    None,
                    2,
                    "planned",
                ),
            ),
        ),
        2,
        "period reason",
    )
    plan = SharedSetupPlan(
        school_plan(),
        (class_plan(current),),
        (roster_plan,),
        standards,
        periods,
    )

    rendered = setup_cli.render_setup_plan(current, plan)

    assert "eng10: REPLACE" in rendered
    assert "Incoming students: 2" in rendered
    assert "Conflicting existing: 1" in rendered
    assert "Existing absent from import: 1" in rendered
    assert "teacher-private-roster.csv" not in rendered
    assert "Student" not in rendered
    assert "s1" not in rendered
    assert "q1 | quarter | Quarter 1" in rendered
    assert "2026-09-01..2026-11-01" in rendered
    assert "parent=none | sequence=1 | lifecycle=planned" in rendered
    assert "q2 | quarter | Quarter 2" in rendered
    assert "Plan is eligible for final APPLY." in rendered


def test_review_requires_exact_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = fake_assessment(tmp_path)
    plan = SharedSetupPlan(school_plan(), (), (), None, None)

    decision = setup_cli.review_setup_plan(
        current,
        plan,
        input_fn=input_reader(["apply", "APPLY"]),
    )

    assert decision is setup_cli.SetupReviewDecision.APPLY
    assert "Type exact APPLY, E, or Q." in capsys.readouterr().out


def test_review_refuses_apply_while_conflict_remains(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = fake_assessment(tmp_path, active_year="2025-2026")
    conflict = school_plan(
        disposition=SchoolYearDisposition.CONFLICT,
    )
    plan = SharedSetupPlan(conflict, (), (), None, None)

    decision = setup_cli.review_setup_plan(
        current,
        plan,
        input_fn=input_reader(["APPLY", "Q"]),
    )

    assert decision is setup_cli.SetupReviewDecision.CANCEL
    assert "APPLY is blocked" in capsys.readouterr().out


def test_collect_requires_explicit_school_year_when_none_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = fake_assessment(tmp_path)
    observed_years: list[str] = []

    def fake_school(_assessment: object, year: str, **_kwargs: object):
        observed_years.append(year)
        return school_plan(year)

    monkeypatch.setattr(setup_cli, "plan_school_year", fake_school)
    monkeypatch.setattr(
        setup_cli,
        "plan_academic_periods",
        lambda *args, **kwargs: AcademicPeriodPlan(
            "2026-2027",
            AcademicPeriodAction.SKIP,
            None,
            0,
            "skipped",
        ),
    )

    result = setup_cli.collect_setup_plan(
        current,
        services=fake_services(),
        input_fn=input_reader(["2026-2027", "", "", "2"]),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.cancelled is False
    assert result.plan is not None
    assert observed_years == ["2026-2027"]
    assert result.plan.school_year.requested_school_year == "2026-2027"
    assert result.plan.classes == ()


def test_collect_uses_existing_active_year_without_inventing_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = fake_assessment(tmp_path, active_year="2026-2027")
    observed_years: list[str] = []

    def fake_school(_assessment: object, year: str, **_kwargs: object):
        observed_years.append(year)
        return school_plan(year, SchoolYearDisposition.EXISTING_MATCH)

    monkeypatch.setattr(setup_cli, "plan_school_year", fake_school)
    monkeypatch.setattr(
        setup_cli,
        "plan_academic_periods",
        lambda *args, **kwargs: AcademicPeriodPlan(
            "2026-2027",
            AcademicPeriodAction.SKIP,
            None,
            0,
            "skipped",
        ),
    )

    result = setup_cli.collect_setup_plan(
        current,
        services=fake_services(),
        input_fn=input_reader(["", "", "2"]),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.plan is not None
    assert observed_years == ["2026-2027"]


def test_collect_class_and_roster_preserves_replace_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = fake_assessment(tmp_path, active_year="2026-2027")
    incoming = FakeRoster(
        "eng10",
        (),
        ("class_id", "student_id", "last_name", "first_name", "period"),
        tmp_path / "roster.csv",
    )
    replacement = RosterPlan(
        "eng10",
        tmp_path / "roster.csv",
        incoming,
        None,
        RosterAction.REPLACE,
        2,
        2,
        1,
        0,
        1,
        1,
        "replacement",
    )
    monkeypatch.setattr(
        setup_cli,
        "plan_school_year",
        lambda *args, **kwargs: school_plan(
            disposition=SchoolYearDisposition.EXISTING_MATCH
        ),
    )
    monkeypatch.setattr(
        setup_cli,
        "plan_class",
        lambda *args, **kwargs: class_plan(current),
    )
    monkeypatch.setattr(
        setup_cli,
        "plan_roster_import",
        lambda *args, **kwargs: replacement,
    )
    monkeypatch.setattr(
        setup_cli,
        "plan_academic_periods",
        lambda *args, **kwargs: AcademicPeriodPlan(
            "2026-2027",
            AcademicPeriodAction.SKIP,
            None,
            0,
            "skipped",
        ),
    )

    result = setup_cli.collect_setup_plan(
        current,
        services=fake_services(),
        input_fn=input_reader(
            ["eng10", str(tmp_path / "roster.csv"), "", "", "2"]
        ),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.plan is not None
    assert result.plan.rosters[0].action is RosterAction.REPLACE


def test_collect_academic_periods_requires_all_explicit_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = fake_assessment(tmp_path, active_year="2026-2027")
    observed_periods: list[object] = []

    monkeypatch.setattr(
        setup_cli,
        "plan_school_year",
        lambda *args, **kwargs: school_plan(
            disposition=SchoolYearDisposition.EXISTING_MATCH
        ),
    )

    def fake_period_plan(
        _assessment: object,
        year: str,
        period_values: object,
        **_kwargs: object,
    ) -> AcademicPeriodPlan:
        if period_values is None:
            return AcademicPeriodPlan(
                year,
                AcademicPeriodAction.SKIP,
                None,
                0,
                "skipped",
            )
        observed_periods.extend(cast(list[object], period_values))
        return AcademicPeriodPlan(
            year,
            AcademicPeriodAction.CREATE,
            FakeCalendar(year, 1, (object(),)),
            1,
            "valid",
        )

    monkeypatch.setattr(setup_cli, "plan_academic_periods", fake_period_plan)

    result = setup_cli.collect_setup_plan(
        current,
        services=fake_services(),
        input_fn=input_reader(
            [
                "",
                "",
                "1",
                "q1",
                "quarter",
                "Quarter 1",
                "2026-09-01",
                "2026-11-01",
                "",
                "not-an-int",
                "1",
                "planned",
                "n",
            ]
        ),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.plan is not None
    assert result.plan.academic_periods is not None
    assert result.plan.academic_periods.action is AcademicPeriodAction.CREATE
    assert observed_periods == [
        {
            "period_id": "q1",
            "period_type": "quarter",
            "label": "Quarter 1",
            "start_date": "2026-09-01",
            "end_date": "2026-11-01",
            "parent_period_id": None,
            "sequence": 1,
            "lifecycle": "planned",
        }
    ]
    output = capsys.readouterr().out
    assert "Allowed period types: quarter, semester" in output
    assert "sequence must be an integer" in output


def test_collect_cancellation_returns_no_plan(
    tmp_path: Path,
) -> None:
    result = setup_cli.collect_setup_plan(
        fake_assessment(tmp_path),
        services=fake_services(),
        input_fn=input_reader(["Q"]),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.cancelled is True
    assert result.plan is None


def test_run_setup_cancel_never_loads_apply_writer_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = fake_assessment(tmp_path, active_year="2026-2027")
    planning = cast(
        CoreClassroomPlanningServices,
        SimpleNamespace(readers=object()),
    )
    plan = SharedSetupPlan(
        school_plan(disposition=SchoolYearDisposition.EXISTING_MATCH),
        (),
        (),
        None,
        None,
    )
    monkeypatch.setattr(setup_cli, "assess_shared_setup", lambda **kwargs: current)
    monkeypatch.setattr(
        setup_cli,
        "collect_setup_plan",
        lambda *args, **kwargs: setup_cli.SetupCollectionResult(plan, False),
    )
    monkeypatch.setattr(
        setup_cli,
        "review_setup_plan",
        lambda *args, **kwargs: setup_cli.SetupReviewDecision.CANCEL,
    )
    apply_loads: list[str] = []

    def load_apply():
        apply_loads.append("loaded")
        return object()

    result = setup_cli.run_classroom_setup(
        planning_services=planning,
        apply_services_loader=load_apply,  # type: ignore[arg-type]
    )

    assert result == 0
    assert apply_loads == []
    assert "No setup changes were made" in capsys.readouterr().out


def test_run_setup_loads_apply_services_only_after_apply_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from paper_data_suite.classroom_apply import SetupApplyResult

    current = fake_assessment(tmp_path, active_year="2026-2027")
    planning = cast(
        CoreClassroomPlanningServices,
        SimpleNamespace(readers=object()),
    )
    plan = SharedSetupPlan(
        school_plan(disposition=SchoolYearDisposition.EXISTING_MATCH),
        (),
        (),
        None,
        None,
    )
    apply_services = object()
    events: list[str] = []
    monkeypatch.setattr(setup_cli, "assess_shared_setup", lambda **kwargs: current)
    monkeypatch.setattr(
        setup_cli,
        "collect_setup_plan",
        lambda *args, **kwargs: setup_cli.SetupCollectionResult(plan, False),
    )
    monkeypatch.setattr(
        setup_cli,
        "review_setup_plan",
        lambda *args, **kwargs: setup_cli.SetupReviewDecision.APPLY,
    )

    def load_apply():
        events.append("load-writers")
        return apply_services

    def execute(*args: object, **kwargs: object) -> SetupApplyResult:
        assert kwargs["services"] is apply_services
        events.append("execute")
        return SetupApplyResult((), ())

    monkeypatch.setattr(setup_cli, "execute_shared_setup_plan", execute)

    result = setup_cli.run_classroom_setup(
        planning_services=planning,
        apply_services_loader=load_apply,  # type: ignore[arg-type]
    )

    assert result == 0
    assert events == ["load-writers", "execute"]
    assert "No persistent changes were needed" in capsys.readouterr().out
