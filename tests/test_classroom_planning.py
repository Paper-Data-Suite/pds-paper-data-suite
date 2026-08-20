from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from paper_data_suite.classroom_planning import (
    AcademicPeriodAction,
    ClassDisposition,
    ClassroomSetupPlanningError,
    CoreClassroomPlanningServices,
    RosterAction,
    RosterSourcePlanningError,
    SchoolYearDisposition,
    StandardsAction,
    assemble_shared_setup_plan,
    load_core_classroom_planning_services,
    plan_academic_periods,
    plan_class,
    plan_roster_import,
    plan_school_year,
    plan_starter_standards,
)
from paper_data_suite.classroom_setup import (
    ClassSetupAssessment,
    CoreClassroomServices,
    SharedSetupAssessment,
)
from paper_data_suite.compatibility import load_release_compatibility_manifest


@dataclass(frozen=True)
class FakeSchoolYearState:
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
    standards: tuple[object, ...]
    profiles: tuple[object, ...]


@dataclass(frozen=True)
class FakeStarterPack:
    pack_id: str
    title: str = "Synthetic pack"
    source: str = "Synthetic"
    grade_bands: tuple[str, ...] = ("9-10",)
    courses: tuple[str, ...] = ("English 10",)
    standard_count: int = 2
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
class FakePeriod:
    period_id: str
    period_type: str
    label: str
    start_date: date
    end_date: date
    parent_period_id: str | None
    sequence: int
    lifecycle: str


@dataclass(frozen=True)
class FakeCalendar:
    school_year: str
    calendar_revision: int
    periods: tuple[object, ...]


class FakeRosterValidationError(ValueError):
    def __init__(self) -> None:
        self.issues = (
            SimpleNamespace(
                code="missing_required_column",
                message="Required column 'student_id' is missing.",
                row_number=1,
                column="student_id",
                value="secret-student-id",
            ),
        )
        super().__init__("invalid roster")


class FakePlanningCore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.rosters: dict[Path, FakeRoster] = {}
        self.starter = FakeLibrary(standards=("s1", "s2"), profiles=("p1",))
        self.merge_result = FakeMergeResult(
            pack_id="starter",
            target_path=root / "standards" / "library.json",
            standards_added=2,
            standards_skipped=0,
            standards_overwritten=0,
            profiles_added=1,
            profiles_skipped=0,
            profiles_overwritten=0,
        )
        self.merged = FakeLibrary(standards=("s1", "s2"), profiles=("p1",))
        self.calendar_validation_error: Exception | None = None
        self.current_calendars: dict[str, FakeCalendar] = {}

    def validate_identifier(self, value: object, field_name: str = "identifier") -> str:
        if not isinstance(value, str) or not value or " " in value:
            raise ValueError(f"{field_name} is invalid")
        return value

    def validate_school_year(self, value: object) -> str:
        if not isinstance(value, str) or len(value) != 9 or value[4] != "-":
            raise ValueError("school_year must use YYYY-YYYY")
        start = int(value[:4])
        end = int(value[5:])
        if end != start + 1:
            raise ValueError("school_year must be consecutive")
        return value

    def create_class_metadata(
        self,
        class_id: str,
        school_year: str,
        *,
        created_at: datetime,
        updated_at: datetime | None = None,
        module_details: dict[str, object] | None = None,
    ) -> FakeMetadata:
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return FakeMetadata(class_id, school_year, module_details or {})

    def load_roster(self, path: str | Path) -> FakeRoster:
        source = Path(path)
        if source.name == "invalid.csv":
            raise FakeRosterValidationError()
        return self.rosters[source]

    def standards_library_path(self, workspace_root: str | Path) -> Path:
        return Path(workspace_root) / "standards" / "library.json"

    def load_starter(self, pack_id: str) -> FakeLibrary:
        assert pack_id == "starter"
        return self.starter

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
        assert Path(target_path) == self.merge_result.target_path
        assert overwrite_conflicts is False
        assert starter_library is self.starter
        assert isinstance(existing_library, FakeLibrary)
        return self.merged, self.merge_result

    def validate_period(self, value: object) -> FakePeriod:
        assert isinstance(value, dict)
        return FakePeriod(
            period_id=cast(str, value["period_id"]),
            period_type=cast(str, value["period_type"]),
            label=cast(str, value["label"]),
            start_date=date.fromisoformat(cast(str, value["start_date"])),
            end_date=date.fromisoformat(cast(str, value["end_date"])),
            parent_period_id=cast(str | None, value["parent_period_id"]),
            sequence=cast(int, value["sequence"]),
            lifecycle=cast(str, value["lifecycle"]),
        )

    def make_calendar(self, **kwargs: object) -> FakeCalendar:
        created_at = cast(datetime, kwargs["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return FakeCalendar(
            school_year=cast(str, kwargs["school_year"]),
            calendar_revision=cast(int, kwargs["calendar_revision"]),
            periods=tuple(cast(tuple[object, ...], kwargs["periods"])),
        )

    def validate_calendar(self, value: object) -> FakeCalendar:
        if self.calendar_validation_error is not None:
            raise self.calendar_validation_error
        return cast(FakeCalendar, value)

    def load_current_calendar(
        self, workspace_root: str | Path, school_year: str
    ) -> FakeCalendar | None:
        assert Path(workspace_root) == self.root
        return self.current_calendars.get(school_year)

    def get_current_revision(
        self, workspace_root: str | Path, school_year: str
    ) -> int | None:
        assert Path(workspace_root) == self.root
        calendar = self.current_calendars.get(school_year)
        return None if calendar is None else calendar.calendar_revision

    def services(self) -> CoreClassroomPlanningServices:
        readers = cast(
            CoreClassroomServices,
            SimpleNamespace(
                load_current_academic_period_calendar=self.load_current_calendar,
                get_current_academic_period_calendar_revision=(
                    self.get_current_revision
                ),
            ),
        )
        return CoreClassroomPlanningServices(
            readers=readers,
            validate_identifier=self.validate_identifier,
            validate_school_year=self.validate_school_year,
            create_class_metadata=self.create_class_metadata,
            load_roster=self.load_roster,
            standards_library_path=self.standards_library_path,
            load_starter_standards_library=self.load_starter,
            merge_standards_libraries=self.merge_standards,
            validate_academic_period=self.validate_period,
            academic_period_calendar_factory=self.make_calendar,
            validate_academic_period_calendar=self.validate_calendar,
            academic_period_calendar_schema_version="1",
            academic_period_calendar_record_type="academic_period_calendar",
            academic_period_types=frozenset({"quarter", "semester"}),
            academic_period_lifecycles=frozenset({"planned", "active", "closed"}),
        )


def assessment(
    root: Path,
    *,
    state: FakeSchoolYearState | None = None,
    classes: tuple[ClassSetupAssessment, ...] = (),
    library: FakeLibrary | None = None,
    packs: tuple[FakeStarterPack, ...] = (FakeStarterPack("starter"),),
    calendar: FakeCalendar | None = None,
) -> SharedSetupAssessment:
    return SharedSetupAssessment(
        workspace_root=root,
        workspace_source="saved_config",
        school_year_state=state,
        classes=classes,
        standards_library=library or FakeLibrary(standards=(), profiles=()),
        starter_standards_packs=packs,
        academic_period_calendar=calendar,
        academic_period_revision=(
            None if calendar is None else calendar.calendar_revision
        ),
    )


def student(student_id: str, *, first_name: str = "Alex") -> FakeStudent:
    return FakeStudent(
        class_id="eng10",
        student_id=student_id,
        last_name="Student",
        first_name=first_name,
        period="2",
        extra_fields={"email": f"{student_id}@example.invalid"},
    )


def roster(
    *students: FakeStudent,
    source: Path | None = None,
    class_id: str = "eng10",
) -> FakeRoster:
    return FakeRoster(
        class_id=class_id,
        students=tuple(students),
        columns=(
            "class_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "email",
        ),
        source_path=source,
    )


def class_assessment(
    root: Path,
    *,
    metadata: FakeMetadata | None,
    existing_roster: FakeRoster | None = None,
) -> ClassSetupAssessment:
    return ClassSetupAssessment(
        class_id="eng10",
        metadata=metadata,
        roster=existing_roster,
    )


def period_input(period_id: str = "q1") -> dict[str, object]:
    return {
        "period_id": period_id,
        "period_type": "quarter",
        "label": "Quarter 1",
        "start_date": "2026-09-01",
        "end_date": "2026-11-01",
        "parent_period_id": None,
        "sequence": 1,
        "lifecycle": "planned",
    }


def test_planning_service_loader_keeps_writers_out_of_pre_apply_surface() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    modules = {
        "pds_core.workspace": SimpleNamespace(
            inspect_workspace_root=lambda explicit_root=None: None,
            ensure_workspace_root=lambda path, create=True: Path(path),
            save_workspace_root=lambda path: Path(path),
            clear_saved_workspace_root=lambda: False,
        ),
        "pds_core.school_years": SimpleNamespace(
            load_school_year_state=lambda root: None,
            validate_school_year=lambda value: value,
            open_school_year=lambda *args, **kwargs: None,
        ),
        "pds_core.classes": SimpleNamespace(
            list_class_folders=lambda root, **kwargs: (),
            load_class_roster=lambda root, class_id: None,
        ),
        "pds_core.class_metadata": SimpleNamespace(
            load_class_metadata_for_class=lambda root, class_id: None,
            create_class_metadata=lambda class_id, school_year, **kwargs: object(),
            write_class_metadata_for_class=lambda *args, **kwargs: None,
        ),
        "pds_core.rosters": SimpleNamespace(
            load_roster=lambda path: None,
            write_class_roster=lambda *args, **kwargs: None,
        ),
        "pds_core.standards": SimpleNamespace(
            load_workspace_standards_library=lambda root: None,
            standards_library_path=(
                lambda root: Path(root) / "standards" / "library.json"
            ),
        ),
        "pds_core.starter_standards": SimpleNamespace(
            list_starter_standards_packs=lambda: (),
            load_starter_standards_library=lambda pack_id: None,
            merge_standards_libraries=lambda *args, **kwargs: (None, None),
            install_starter_standards_library=lambda *args, **kwargs: None,
        ),
        "pds_core.academic_period_storage": SimpleNamespace(
            load_current_academic_period_calendar=lambda root, year: None,
            get_current_academic_period_calendar_revision=lambda root, year: None,
            write_academic_period_calendar=lambda *args, **kwargs: None,
        ),
        "pds_core.identifiers": SimpleNamespace(
            validate_identifier=lambda value, field_name="identifier": value,
        ),
        "pds_core.academic_periods": SimpleNamespace(
            validate_academic_period=lambda value: value,
            AcademicPeriodCalendar=lambda **kwargs: SimpleNamespace(**kwargs),
            validate_academic_period_calendar=lambda value: value,
            ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION="1",
            ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE="academic_period_calendar",
            ACADEMIC_PERIOD_TYPES=frozenset({"quarter"}),
            ACADEMIC_PERIOD_LIFECYCLES=frozenset({"planned"}),
        ),
    }

    services = load_core_classroom_planning_services(
        manifest,
        version_lookup=lambda _distribution: core.version,
        module_importer=lambda name: modules[name],
    )

    assert services.academic_period_types == frozenset({"quarter"})
    assert not hasattr(services, "open_school_year")
    assert not hasattr(services, "write_class_metadata_for_class")
    assert not hasattr(services, "write_class_roster")
    assert not hasattr(services, "install_starter_standards_library")
    assert not hasattr(services, "write_academic_period_calendar")


def test_school_year_plan_new_match_and_conflict(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    empty = assessment(tmp_path)
    current = assessment(
        tmp_path,
        state=FakeSchoolYearState(
            "2026-2027",
            datetime(2026, 8, 20, tzinfo=UTC),
        ),
    )

    new = plan_school_year(empty, "2026-2027", services=core.services())
    match = plan_school_year(current, "2026-2027", services=core.services())
    conflict = plan_school_year(current, "2027-2028", services=core.services())

    assert new.disposition is SchoolYearDisposition.NEW
    assert match.disposition is SchoolYearDisposition.EXISTING_MATCH
    assert conflict.disposition is SchoolYearDisposition.CONFLICT
    assert conflict.blocks_apply is True


def test_school_year_plan_uses_core_validation(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    with pytest.raises(ClassroomSetupPlanningError, match="Core rejected"):
        plan_school_year(assessment(tmp_path), "2026-2028", services=core.services())


def test_class_plan_new_and_existing_match(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    empty = assessment(tmp_path)
    current = assessment(
        tmp_path,
        classes=(
            class_assessment(
                tmp_path,
                metadata=FakeMetadata("eng10", "2026-2027", {"keep": True}),
            ),
        ),
    )

    new = plan_class(
        empty,
        "eng10",
        "2026-2027",
        planning_time=now,
        services=core.services(),
    )
    match = plan_class(
        current,
        "eng10",
        "2026-2027",
        planning_time=now,
        services=core.services(),
    )

    assert new.disposition is ClassDisposition.NEW
    assert new.candidate_metadata.module_details == {}
    assert match.disposition is ClassDisposition.EXISTING_MATCH
    assert match.candidate_metadata.module_details == {"keep": True}


def test_class_plan_allows_empty_folder_but_refuses_roster_without_metadata(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    folder_only = assessment(
        tmp_path,
        classes=(class_assessment(tmp_path, metadata=None),),
    )
    orphan_roster = assessment(
        tmp_path,
        classes=(
            class_assessment(
                tmp_path,
                metadata=None,
                existing_roster=roster(student("s1")),
            ),
        ),
    )

    finish = plan_class(
        folder_only,
        "eng10",
        "2026-2027",
        planning_time=now,
        services=core.services(),
    )
    refuse = plan_class(
        orphan_roster,
        "eng10",
        "2026-2027",
        planning_time=now,
        services=core.services(),
    )

    assert finish.disposition is ClassDisposition.NEW
    assert refuse.disposition is ClassDisposition.CONFLICT


def test_class_plan_refuses_existing_metadata_for_other_year(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    current = assessment(
        tmp_path,
        classes=(
            class_assessment(
                tmp_path,
                metadata=FakeMetadata("eng10", "2025-2026", {}),
            ),
        ),
    )

    plan = plan_class(
        current,
        "eng10",
        "2026-2027",
        planning_time=datetime(2026, 8, 20, tzinfo=UTC),
        services=core.services(),
    )

    assert plan.disposition is ClassDisposition.CONFLICT
    assert plan.blocks_apply is True


def test_roster_plan_reports_core_validation_diagnostics(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)

    with pytest.raises(RosterSourcePlanningError) as caught:
        plan_roster_import(
            assessment(tmp_path),
            "eng10",
            tmp_path / "invalid.csv",
            services=core.services(),
        )

    assert caught.value.diagnostics == (
        "row 1 / column student_id: A required roster column is missing.",
    )
    assert "secret-student-id" not in str(caught.value)
    assert "secret-student-id" not in "\n".join(caught.value.diagnostics)


def test_roster_plan_refuses_source_for_different_class(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    source = tmp_path / "other.csv"
    core.rosters[source] = roster(student("s1"), source=source, class_id="eng11")

    plan = plan_roster_import(
        assessment(tmp_path),
        "eng10",
        source,
        services=core.services(),
    )

    assert plan.action is RosterAction.REFUSE
    assert plan.blocks_apply is True


def test_roster_plan_create_when_no_existing_roster(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    source = tmp_path / "new.csv"
    core.rosters[source] = roster(student("s1"), student("s2"), source=source)

    plan = plan_roster_import(
        assessment(tmp_path),
        "eng10",
        source,
        services=core.services(),
    )

    assert plan.action is RosterAction.CREATE
    assert plan.incoming_student_count == 2
    assert plan.existing_student_count is None
    assert plan.new_count == 2


def test_roster_plan_keep_ignores_only_source_path(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    source = tmp_path / "incoming.csv"
    incoming = roster(student("s1"), source=source)
    existing = roster(
        student("s1"),
        source=tmp_path / "classes" / "eng10" / "roster.csv",
    )
    core.rosters[source] = incoming
    current = assessment(
        tmp_path,
        classes=(
            class_assessment(
                tmp_path,
                metadata=FakeMetadata("eng10", "2026-2027", {}),
                existing_roster=existing,
            ),
        ),
    )

    plan = plan_roster_import(current, "eng10", source, services=core.services())

    assert plan.action is RosterAction.KEEP
    assert plan.unchanged_count == 1
    assert plan.conflicting_existing_count == 0


def test_roster_plan_replace_uses_student_id_and_reports_counts(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    source = tmp_path / "incoming.csv"
    core.rosters[source] = roster(
        student("s1"),
        student("s2", first_name="Changed"),
        student("s3"),
        source=source,
    )
    existing = roster(
        student("s1"),
        student("s2"),
        student("s4"),
        source=tmp_path / "canonical.csv",
    )
    current = assessment(
        tmp_path,
        classes=(
            class_assessment(
                tmp_path,
                metadata=FakeMetadata("eng10", "2026-2027", {}),
                existing_roster=existing,
            ),
        ),
    )

    plan = plan_roster_import(current, "eng10", source, services=core.services())

    assert plan.action is RosterAction.REPLACE
    assert plan.new_count == 1
    assert plan.unchanged_count == 1
    assert plan.conflicting_existing_count == 1
    assert plan.removed_existing_count == 1


def test_standards_plan_requires_explicit_advertised_pack(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    with pytest.raises(ClassroomSetupPlanningError, match="not advertised"):
        plan_starter_standards(
            assessment(tmp_path),
            "not-a-pack",
            services=core.services(),
        )


def test_standards_plan_install_keep_and_refuse(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    current = assessment(tmp_path)

    install = plan_starter_standards(current, "starter", services=core.services())
    assert install.action is StandardsAction.INSTALL
    assert install.standards_to_add == 2
    assert install.profiles_to_add == 1

    core.merge_result = FakeMergeResult(
        pack_id="starter",
        target_path=tmp_path / "standards" / "library.json",
        standards_added=0,
        standards_skipped=2,
        standards_overwritten=0,
        profiles_added=0,
        profiles_skipped=1,
        profiles_overwritten=0,
    )
    keep = plan_starter_standards(current, "starter", services=core.services())
    assert keep.action is StandardsAction.KEEP
    assert keep.standards_identical == 2

    core.merge_result = FakeMergeResult(
        pack_id="starter",
        target_path=tmp_path / "standards" / "library.json",
        standards_added=0,
        standards_skipped=1,
        standards_overwritten=0,
        profiles_added=0,
        profiles_skipped=0,
        profiles_overwritten=0,
        standard_conflicts=("std.conflict",),
        profile_conflicts=("profile.conflict",),
    )
    refuse = plan_starter_standards(current, "starter", services=core.services())
    assert refuse.action is StandardsAction.REFUSE
    assert refuse.standard_conflicts == ("std.conflict",)
    assert refuse.profile_conflicts == ("profile.conflict",)


def test_academic_period_plan_skip_and_existing_keep(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    skipped = plan_academic_periods(
        assessment(tmp_path),
        "2026-2027",
        None,
        planning_time=datetime(2026, 8, 20, tzinfo=UTC),
        services=core.services(),
    )
    existing_calendar = FakeCalendar("2026-2027", 1, (object(), object()))
    kept = plan_academic_periods(
        assessment(tmp_path, calendar=existing_calendar),
        "2026-2027",
        None,
        planning_time=datetime(2026, 8, 20, tzinfo=UTC),
        services=core.services(),
    )

    assert skipped.action is AcademicPeriodAction.SKIP
    assert kept.action is AcademicPeriodAction.KEEP
    assert kept.period_count == 2


def test_academic_period_plan_refuses_revision_of_existing_calendar(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    existing_calendar = FakeCalendar("2026-2027", 1, (object(),))

    plan = plan_academic_periods(
        assessment(tmp_path, calendar=existing_calendar),
        "2026-2027",
        (period_input(),),
        planning_time=datetime(2026, 8, 20, tzinfo=UTC),
        services=core.services(),
    )

    assert plan.action is AcademicPeriodAction.REFUSE
    assert plan.blocks_apply is True


def test_academic_period_plan_builds_revision_one_and_uses_full_core_validation(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)

    plan = plan_academic_periods(
        assessment(tmp_path),
        "2026-2027",
        (period_input(),),
        planning_time=now,
        services=core.services(),
    )

    assert plan.action is AcademicPeriodAction.CREATE
    assert plan.candidate_calendar is not None
    assert plan.candidate_calendar.calendar_revision == 1
    assert plan.period_count == 1

    core.calendar_validation_error = ValueError("duplicate sibling sequence")
    with pytest.raises(ClassroomSetupPlanningError, match="duplicate sibling sequence"):
        plan_academic_periods(
            assessment(tmp_path),
            "2026-2027",
            (period_input(),),
            planning_time=now,
            services=core.services(),
        )


def test_assembled_plan_blocks_any_unresolved_domain_conflict(tmp_path: Path) -> None:
    core = FakePlanningCore(tmp_path)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    current = assessment(
        tmp_path,
        state=FakeSchoolYearState("2025-2026", now),
    )
    school = plan_school_year(current, "2026-2027", services=core.services())
    class_plan = plan_class(
        current,
        "eng10",
        "2026-2027",
        planning_time=now,
        services=core.services(),
    )

    plan = assemble_shared_setup_plan(school, classes=(class_plan,))

    assert plan.can_apply is False
    assert plan.blocking_reasons


def test_assembled_plan_rejects_roster_without_corresponding_class_plan(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    source = tmp_path / "incoming.csv"
    core.rosters[source] = roster(student("s1"), source=source)
    school = plan_school_year(
        assessment(tmp_path),
        "2026-2027",
        services=core.services(),
    )
    roster_plan = plan_roster_import(
        assessment(tmp_path),
        "eng10",
        source,
        services=core.services(),
    )

    with pytest.raises(ClassroomSetupPlanningError, match="no corresponding class"):
        assemble_shared_setup_plan(school, rosters=(roster_plan,))


def test_academic_period_plan_checks_proposed_year_when_not_active(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    existing = FakeCalendar("2026-2027", 1, (object(),))
    core.current_calendars["2026-2027"] = existing

    plan = plan_academic_periods(
        assessment(tmp_path),
        "2026-2027",
        None,
        planning_time=datetime(2026, 8, 20, tzinfo=UTC),
        services=core.services(),
    )

    assert plan.action is AcademicPeriodAction.KEEP
    assert plan.candidate_calendar is existing


def test_academic_period_plan_fails_closed_on_pointer_mismatch(
    tmp_path: Path,
) -> None:
    core = FakePlanningCore(tmp_path)
    existing = FakeCalendar("2026-2027", 2, (object(),))
    core.current_calendars["2026-2027"] = existing

    services = core.services()
    readers = cast(
        CoreClassroomServices,
        SimpleNamespace(
            load_current_academic_period_calendar=core.load_current_calendar,
            get_current_academic_period_calendar_revision=(
                lambda root, year: 1
            ),
        ),
    )
    mismatched_services = CoreClassroomPlanningServices(
        readers=readers,
        validate_identifier=services.validate_identifier,
        validate_school_year=services.validate_school_year,
        create_class_metadata=services.create_class_metadata,
        load_roster=services.load_roster,
        standards_library_path=services.standards_library_path,
        load_starter_standards_library=(
            services.load_starter_standards_library
        ),
        merge_standards_libraries=services.merge_standards_libraries,
        validate_academic_period=services.validate_academic_period,
        academic_period_calendar_factory=(
            services.academic_period_calendar_factory
        ),
        validate_academic_period_calendar=(
            services.validate_academic_period_calendar
        ),
        academic_period_calendar_schema_version=(
            services.academic_period_calendar_schema_version
        ),
        academic_period_calendar_record_type=(
            services.academic_period_calendar_record_type
        ),
        academic_period_types=services.academic_period_types,
        academic_period_lifecycles=services.academic_period_lifecycles,
    )

    with pytest.raises(ClassroomSetupPlanningError, match="pointer disagree"):
        plan_academic_periods(
            assessment(tmp_path),
            "2026-2027",
            None,
            planning_time=datetime(2026, 8, 20, tzinfo=UTC),
            services=mismatched_services,
        )
