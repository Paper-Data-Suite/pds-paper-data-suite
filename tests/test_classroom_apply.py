from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import paper_data_suite.classroom_apply as classroom_apply
from paper_data_suite.classroom_apply import (
    ClassroomSetupPartialSuccessError,
    ClassroomSetupPreflightError,
    CoreClassroomApplyServices,
    execute_shared_setup_plan,
    load_core_classroom_apply_services,
)
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
    CoreClassroomServices,
    SharedSetupAssessment,
)


@dataclass(frozen=True)
class FakeState:
    active_school_year: str
    opened_at: datetime
    closed_at: datetime | None = None


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
class FakeLibrary:
    standards: tuple[object, ...] = ()
    profiles: tuple[object, ...] = ()


@dataclass(frozen=True)
class FakePack:
    pack_id: str = "starter"
    title: str = "Synthetic starter"
    source: str = "Synthetic"
    grade_bands: tuple[str, ...] = ("9-10",)
    courses: tuple[str, ...] = ("English",)
    standard_count: int = 1
    profile_count: int = 1


@dataclass(frozen=True)
class FakeMergeResult:
    pack_id: str
    target_path: Path
    standards_added: int
    standards_skipped: int
    standards_overwritten: int
    profiles_added: int
    profiles_skipped: int
    profiles_overwritten: int
    standard_conflicts: tuple[str, ...] = ()
    profile_conflicts: tuple[str, ...] = ()

    @property
    def has_conflicts(self) -> bool:
        return bool(self.standard_conflicts or self.profile_conflicts)

    @property
    def changed_count(self) -> int:
        return (
            self.standards_added
            + self.standards_overwritten
            + self.profiles_added
            + self.profiles_overwritten
        )


@dataclass(frozen=True)
class FakeCalendar:
    school_year: str
    calendar_revision: int
    periods: tuple[object, ...]


class FakeApplyCore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state: FakeState | None = None
        self.metadata: dict[str, FakeMetadata] = {}
        self.rosters: dict[str, FakeRoster] = {}
        self.roster_sources: dict[Path, FakeRoster] = {}
        self.standards = FakeLibrary()
        self.starter = FakeLibrary(("s1",), ("p1",))
        self.calendar: FakeCalendar | None = None
        self.events: list[str] = []
        self.fail_class_write = False
        self.drift_roster_on_open: str | None = None

    def readers(self) -> CoreClassroomServices:
        return cast(
            CoreClassroomServices,
            SimpleNamespace(
                load_school_year_state=lambda root: self.state,
                load_class_metadata_for_class=(
                    lambda root, class_id: self.metadata[class_id]
                ),
                load_class_roster=lambda root, class_id: self.rosters[class_id],
                load_workspace_standards_library=lambda root: self.standards,
                load_current_academic_period_calendar=(
                    lambda root, year: self.calendar
                    if self.calendar is not None
                    and self.calendar.school_year == year
                    else None
                ),
                get_current_academic_period_calendar_revision=(
                    lambda root, year: self.calendar.calendar_revision
                    if self.calendar is not None
                    and self.calendar.school_year == year
                    else None
                ),
            ),
        )

    def planning(self) -> CoreClassroomPlanningServices:
        return cast(
            CoreClassroomPlanningServices,
            SimpleNamespace(
                readers=self.readers(),
                create_class_metadata=self.create_metadata,
                load_roster=lambda path: self.roster_sources[Path(path)],
                standards_library_path=(
                    lambda root: Path(root) / "standards" / "library.json"
                ),
                load_starter_standards_library=lambda pack_id: self.starter,
                merge_standards_libraries=self.merge_standards,
            ),
        )

    def create_metadata(
        self,
        class_id: str,
        school_year: str,
        *,
        created_at: datetime,
        updated_at: datetime | None = None,
        module_details: dict[str, object] | None = None,
    ) -> FakeMetadata:
        assert created_at.tzinfo is not None
        return FakeMetadata(class_id, school_year, module_details or {})

    def merge_standards(
        self,
        pack_id: str,
        target_path: str | Path,
        existing_library: FakeLibrary,
        starter_library: FakeLibrary,
        *,
        overwrite_conflicts: bool = False,
    ) -> tuple[FakeLibrary, FakeMergeResult]:
        assert pack_id == "starter"
        assert overwrite_conflicts is False
        assert starter_library == self.starter
        candidate = FakeLibrary(
            existing_library.standards + ("s1",),
            existing_library.profiles + ("p1",),
        )
        result = FakeMergeResult(
            pack_id="starter",
            target_path=Path(target_path),
            standards_added=1,
            standards_skipped=0,
            standards_overwritten=0,
            profiles_added=1,
            profiles_skipped=0,
            profiles_overwritten=0,
        )
        return candidate, result

    def open_school_year(
        self,
        root: str | Path,
        school_year: str,
        *,
        opened_at: datetime,
        overwrite: bool = False,
    ) -> FakeState:
        assert Path(root) == self.root
        assert overwrite is False
        self.events.append("school")
        self.state = FakeState(school_year, opened_at)
        if self.drift_roster_on_open is not None:
            class_id = self.drift_roster_on_open
            current = self.rosters[class_id]
            student = current.students[0]
            self.rosters[class_id] = FakeRoster(
                class_id,
                (
                    FakeStudent(
                        class_id,
                        student.student_id,
                        "Changed",
                        student.first_name,
                        student.period,
                        student.extra_fields,
                    ),
                ),
                current.columns,
            )
        return self.state

    def write_metadata(
        self,
        root: str | Path,
        metadata_value: FakeMetadata,
        *,
        overwrite: bool = False,
    ) -> Path:
        assert overwrite is False
        self.events.append(f"class:{metadata_value.class_id}")
        if self.fail_class_write:
            raise ValueError("synthetic class write failure")
        self.metadata[metadata_value.class_id] = metadata_value
        return self.root / "classes" / metadata_value.class_id / "class.json"

    def write_roster(
        self,
        root: str | Path,
        roster: FakeRoster,
        *,
        overwrite: bool = False,
    ) -> Path:
        self.events.append(
            f"roster:{'replace' if overwrite else 'create'}:{roster.class_id}"
        )
        self.rosters[roster.class_id] = roster
        return self.root / "classes" / roster.class_id / "roster.csv"

    def install_standards(
        self,
        root: str | Path,
        pack_id: str,
        existing_library: FakeLibrary,
        *,
        overwrite_conflicts: bool = False,
    ) -> FakeMergeResult:
        assert overwrite_conflicts is False
        self.events.append("standards")
        candidate, result = self.merge_standards(
            pack_id,
            self.root / "standards" / "library.json",
            existing_library,
            self.starter,
            overwrite_conflicts=False,
        )
        self.standards = candidate
        return result

    def write_calendar(
        self,
        root: str | Path,
        calendar: FakeCalendar,
        *,
        expected_current_revision: int | None,
    ) -> Path:
        assert expected_current_revision is None
        self.events.append("periods")
        self.calendar = calendar
        return self.root / "settings" / "academic_periods" / "1.json"

    def services(self) -> CoreClassroomApplyServices:
        return CoreClassroomApplyServices(
            planning=self.planning(),
            open_school_year=self.open_school_year,
            write_class_metadata_for_class=cast(object, self.write_metadata),
            write_class_roster=cast(object, self.write_roster),
            install_starter_standards_library=cast(
                object,
                self.install_standards,
            ),
            write_academic_period_calendar=cast(object, self.write_calendar),
        )


def assessment(
    core: FakeApplyCore,
    *,
    classes: tuple[ClassSetupAssessment, ...] = (),
) -> SharedSetupAssessment:
    return SharedSetupAssessment(
        workspace_root=core.root,
        workspace_source="saved_config",
        school_year_state=core.state,
        classes=classes,
        standards_library=core.standards,
        starter_standards_packs=(FakePack(),),
        academic_period_calendar=core.calendar,
        academic_period_revision=(
            None if core.calendar is None else core.calendar.calendar_revision
        ),
    )


def school_plan(
    disposition: SchoolYearDisposition = SchoolYearDisposition.NEW,
) -> SchoolYearPlan:
    return SchoolYearPlan("2026-2027", disposition, "school")


def test_apply_services_load_writers_from_actual_public_owner_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning = cast(CoreClassroomPlanningServices, SimpleNamespace())
    monkeypatch.setattr(
        classroom_apply,
        "load_core_classroom_planning_services",
        lambda *args, **kwargs: planning,
    )
    modules = {
        "pds_core.school_years": SimpleNamespace(open_school_year=lambda *a, **k: None),
        "pds_core.classes": SimpleNamespace(write_class_roster=lambda *a, **k: None),
        "pds_core.class_metadata": SimpleNamespace(
            write_class_metadata_for_class=lambda *a, **k: None
        ),
        "pds_core.starter_standards": SimpleNamespace(
            install_starter_standards_library=lambda *a, **k: None
        ),
        "pds_core.academic_period_storage": SimpleNamespace(
            write_academic_period_calendar=lambda *a, **k: None
        ),
    }
    events: list[str] = []

    def importer(name: str) -> object:
        events.append(name)
        return modules[name]

    services = load_core_classroom_apply_services(module_importer=importer)

    assert services.planning is planning
    assert events == [
        "pds_core.school_years",
        "pds_core.classes",
        "pds_core.class_metadata",
        "pds_core.starter_standards",
        "pds_core.academic_period_storage",
    ]


def test_preflight_state_drift_refuses_every_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    reviewed = assessment(core)
    changed = SharedSetupAssessment(
        workspace_root=tmp_path,
        workspace_source="saved_config",
        school_year_state=None,
        classes=(),
        standards_library=FakeLibrary(("external",), ()),
        starter_standards_packs=(FakePack(),),
        academic_period_calendar=None,
        academic_period_revision=None,
    )
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: changed)

    with pytest.raises(ClassroomSetupPreflightError, match="changed after review"):
        execute_shared_setup_plan(
            reviewed,
            SharedSetupPlan(school_plan(), (), (), None, None),
            services=core.services(),
            clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
        )

    assert core.events == []
    assert core.state is None


def test_apply_executes_core_writes_in_required_order_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    incoming = FakeRoster(
        "eng10",
        (FakeStudent("eng10", "s1", "Last", "First", "2", {}),),
        ("class_id", "student_id", "last_name", "first_name", "period"),
        tmp_path / "incoming.csv",
    )
    core.roster_sources[incoming.source_path] = incoming  # type: ignore[index]
    reviewed = assessment(core)
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: reviewed)

    class_plan = ClassPlan(
        "eng10",
        "2026-2027",
        ClassDisposition.NEW,
        FakeMetadata("eng10", "2026-2027", {}),
        None,
        "new class",
    )
    roster_plan = RosterPlan(
        "eng10",
        cast(Path, incoming.source_path),
        incoming,
        None,
        RosterAction.CREATE,
        1,
        None,
        1,
        0,
        0,
        0,
        "create roster",
    )
    standards = StandardsPlan(
        "starter",
        StandardsAction.INSTALL,
        FakeLibrary(("s1",), ("p1",)),
        tmp_path / "standards" / "library.json",
        1,
        0,
        (),
        1,
        0,
        (),
        "install",
    )
    calendar = FakeCalendar("2026-2027", 1, ("q1",))
    periods = AcademicPeriodPlan(
        "2026-2027",
        AcademicPeriodAction.CREATE,
        calendar,
        1,
        "create calendar",
    )
    plan = SharedSetupPlan(
        school_plan(),
        (class_plan,),
        (roster_plan,),
        standards,
        periods,
    )

    result = execute_shared_setup_plan(
        reviewed,
        plan,
        services=core.services(),
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=UTC),
    )

    assert core.events == [
        "school",
        "class:eng10",
        "roster:create:eng10",
        "standards",
        "periods",
    ]
    assert result.changed_actions == (
        "school_year:OPEN:2026-2027",
        "class:CREATE:eng10",
        "roster:CREATE:eng10",
        "standards:INSTALL:starter",
        "academic_periods:CREATE:2026-2027:revision-1",
    )


def test_roster_source_change_after_review_fails_before_first_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    source = tmp_path / "incoming.csv"
    reviewed_roster = FakeRoster(
        "eng10",
        (FakeStudent("eng10", "s1", "Last", "First", "2", {}),),
        ("class_id", "student_id", "last_name", "first_name", "period"),
        source,
    )
    core.roster_sources[source] = FakeRoster(
        "eng10",
        (FakeStudent("eng10", "s1", "Changed", "First", "2", {}),),
        reviewed_roster.columns,
        source,
    )
    reviewed = assessment(core)
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: reviewed)
    plan = SharedSetupPlan(
        school_plan(),
        (
            ClassPlan(
                "eng10",
                "2026-2027",
                ClassDisposition.NEW,
                FakeMetadata("eng10", "2026-2027", {}),
                None,
                "new",
            ),
        ),
        (
            RosterPlan(
                "eng10",
                source,
                reviewed_roster,
                None,
                RosterAction.CREATE,
                1,
                None,
                1,
                0,
                0,
                0,
                "create",
            ),
        ),
        None,
        None,
    )

    with pytest.raises(ClassroomSetupPreflightError, match="source.*changed"):
        execute_shared_setup_plan(
            reviewed,
            plan,
            services=core.services(),
            clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
        )

    assert core.events == []


def test_late_roster_drift_reports_partial_success_without_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    existing = FakeRoster(
        "eng10",
        (FakeStudent("eng10", "s1", "Old", "First", "2", {}),),
        ("class_id", "student_id", "last_name", "first_name", "period"),
    )
    incoming = FakeRoster(
        "eng10",
        (FakeStudent("eng10", "s1", "New", "First", "2", {}),),
        existing.columns,
        tmp_path / "incoming.csv",
    )
    metadata_value = FakeMetadata("eng10", "2026-2027", {})
    core.metadata["eng10"] = metadata_value
    core.rosters["eng10"] = existing
    core.roster_sources[cast(Path, incoming.source_path)] = incoming
    current_class = ClassSetupAssessment("eng10", metadata_value, existing)
    reviewed = assessment(core, classes=(current_class,))
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: reviewed)
    core.drift_roster_on_open = "eng10"
    plan = SharedSetupPlan(
        school_plan(),
        (
            ClassPlan(
                "eng10",
                "2026-2027",
                ClassDisposition.EXISTING_MATCH,
                metadata_value,
                current_class,
                "match",
            ),
        ),
        (
            RosterPlan(
                "eng10",
                cast(Path, incoming.source_path),
                incoming,
                existing,
                RosterAction.REPLACE,
                1,
                1,
                0,
                0,
                1,
                0,
                "replace",
            ),
        ),
        None,
        None,
    )

    with pytest.raises(ClassroomSetupPartialSuccessError) as raised:
        execute_shared_setup_plan(
            reviewed,
            plan,
            services=core.services(),
            clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
        )

    assert raised.value.changed_actions == ("school_year:OPEN:2026-2027",)
    assert not any(event.startswith("roster:replace") for event in core.events)
    assert "no rollback" in str(raised.value).lower()


def test_later_writer_failure_reports_earlier_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    reviewed = assessment(core)
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: reviewed)
    core.fail_class_write = True
    plan = SharedSetupPlan(
        school_plan(),
        (
            ClassPlan(
                "eng10",
                "2026-2027",
                ClassDisposition.NEW,
                FakeMetadata("eng10", "2026-2027", {}),
                None,
                "new",
            ),
        ),
        (),
        None,
        None,
    )

    with pytest.raises(ClassroomSetupPartialSuccessError) as raised:
        execute_shared_setup_plan(
            reviewed,
            plan,
            services=core.services(),
            clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
        )

    assert raised.value.changed_actions == ("school_year:OPEN:2026-2027",)
    assert core.state is not None
    assert "eng10" not in core.metadata


def test_idempotent_reviewed_keep_plan_performs_no_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = FakeApplyCore(tmp_path)
    core.state = FakeState(
        "2026-2027",
        datetime(2026, 8, 1, tzinfo=UTC),
    )
    reviewed = assessment(core)
    monkeypatch.setattr(classroom_apply, "assess_shared_setup", lambda **kw: reviewed)
    plan = SharedSetupPlan(
        school_plan(SchoolYearDisposition.EXISTING_MATCH),
        (),
        (),
        None,
        AcademicPeriodPlan(
            "2026-2027",
            AcademicPeriodAction.SKIP,
            None,
            0,
            "skip",
        ),
    )

    result = execute_shared_setup_plan(
        reviewed,
        plan,
        services=core.services(),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert result.changed_actions == ()
    assert core.events == []


def test_apply_services_match_installed_qualified_core_public_contract() -> None:
    services = load_core_classroom_apply_services()

    assert callable(services.open_school_year)
    assert callable(services.write_class_metadata_for_class)
    assert callable(services.write_class_roster)
    assert callable(services.install_starter_standards_library)
    assert callable(services.write_academic_period_calendar)
