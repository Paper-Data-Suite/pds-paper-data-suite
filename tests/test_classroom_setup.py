from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from paper_data_suite.classroom_setup import (
    ClassroomSetupAssessmentError,
    ClassroomWorkspaceError,
    CoreClassroomServiceError,
    CoreClassroomServices,
    assess_shared_setup,
    load_core_classroom_services,
)
from paper_data_suite.compatibility import load_release_compatibility_manifest


@dataclass(frozen=True)
class FakeWorkspaceStatus:
    root: Path
    source: str = "saved_config"
    exists: bool = True
    is_dir: bool = True
    is_writable: bool = True


@dataclass(frozen=True)
class FakeSchoolYearState:
    active_school_year: str
    opened_at: datetime
    closed_at: datetime | None = None


@dataclass(frozen=True)
class FakeClassFolder:
    class_id: str
    class_dir: Path
    roster_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class FakeClassMetadata:
    class_id: str
    school_year: str
    module_details: dict[str, object]


@dataclass(frozen=True)
class FakeStudent:
    student_id: str


@dataclass(frozen=True)
class FakeRoster:
    class_id: str
    students: tuple[FakeStudent, ...]
    columns: tuple[str, ...] = (
        "class_id",
        "student_id",
        "last_name",
        "first_name",
        "period",
    )


@dataclass(frozen=True)
class FakeStandardsLibrary:
    standards: tuple[object, ...]
    profiles: tuple[object, ...]


@dataclass(frozen=True)
class FakeStarterPack:
    pack_id: str
    title: str
    source: str
    grade_bands: tuple[str, ...]
    courses: tuple[str, ...]
    standard_count: int
    profile_count: int


@dataclass(frozen=True)
class FakeCalendar:
    school_year: str
    calendar_revision: int
    periods: tuple[object, ...]


class FakeCore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.workspace = FakeWorkspaceStatus(root=root)
        self.school_year: FakeSchoolYearState | None = None
        self.folders: tuple[FakeClassFolder, ...] = ()
        self.metadata_by_class: dict[str, FakeClassMetadata] = {}
        self.roster_by_class: dict[str, FakeRoster] = {}
        self.standards = FakeStandardsLibrary(standards=(), profiles=())
        self.starter_packs: tuple[FakeStarterPack, ...] = ()
        self.calendar: FakeCalendar | None = None
        self.revision: int | None = None
        self.calls: list[str] = []
        self.fail_area: str | None = None

    def inspect_workspace(
        self, explicit_root: str | Path | None = None
    ) -> FakeWorkspaceStatus:
        assert explicit_root is None
        self.calls.append("workspace.inspect")
        return self.workspace

    def load_school_year(
        self, workspace_root: str | Path
    ) -> FakeSchoolYearState | None:
        assert Path(workspace_root) == self.root
        self.calls.append("school_year.load")
        if self.fail_area == "school_year":
            raise ValueError("bad school year")
        return self.school_year

    def list_classes(
        self,
        workspace_root: str | Path,
        *,
        require_roster: bool = False,
        load_rosters: bool = False,
        require_metadata: bool = False,
        load_metadata: bool = False,
    ) -> tuple[FakeClassFolder, ...]:
        assert Path(workspace_root) == self.root
        assert not require_roster
        assert not load_rosters
        assert not require_metadata
        assert not load_metadata
        self.calls.append("classes.list")
        return self.folders

    def load_metadata(
        self, workspace_root: str | Path, class_id: str
    ) -> FakeClassMetadata:
        assert Path(workspace_root) == self.root
        self.calls.append(f"class.metadata:{class_id}")
        if self.fail_area == f"metadata:{class_id}":
            raise ValueError("invalid class.json")
        return self.metadata_by_class[class_id]

    def load_roster(self, workspace_root: str | Path, class_id: str) -> FakeRoster:
        assert Path(workspace_root) == self.root
        self.calls.append(f"class.roster:{class_id}")
        if self.fail_area == f"roster:{class_id}":
            raise ValueError("invalid roster.csv")
        return self.roster_by_class[class_id]

    def load_standards(self, workspace_root: str | Path) -> FakeStandardsLibrary:
        assert Path(workspace_root) == self.root
        self.calls.append("standards.load")
        if self.fail_area == "standards":
            raise ValueError("invalid standards library")
        return self.standards

    def list_starter_packs(self) -> tuple[FakeStarterPack, ...]:
        self.calls.append("standards.starters")
        return self.starter_packs

    def load_calendar(
        self,
        workspace_root: str | Path,
        school_year: str,
    ) -> FakeCalendar | None:
        assert Path(workspace_root) == self.root
        self.calls.append(f"periods.load:{school_year}")
        if self.fail_area == "periods":
            raise ValueError("bad calendar")
        return self.calendar

    def get_revision(self, workspace_root: str | Path, school_year: str) -> int | None:
        assert Path(workspace_root) == self.root
        self.calls.append(f"periods.revision:{school_year}")
        return self.revision

    def services(self) -> CoreClassroomServices:
        return CoreClassroomServices(
            inspect_workspace_root=self.inspect_workspace,
            load_school_year_state=self.load_school_year,
            list_class_folders=self.list_classes,
            load_class_metadata_for_class=self.load_metadata,
            load_class_roster=self.load_roster,
            load_workspace_standards_library=self.load_standards,
            list_starter_standards_packs=self.list_starter_packs,
            load_current_academic_period_calendar=self.load_calendar,
            get_current_academic_period_calendar_revision=self.get_revision,
        )


def test_load_services_qualifies_core_before_other_core_imports() -> None:
    manifest = load_release_compatibility_manifest()
    core = next(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    events: list[str] = []

    modules = {
        "pds_core.workspace": SimpleNamespace(
            inspect_workspace_root=lambda explicit_root=None: None,
            ensure_workspace_root=lambda path, create=True: Path(path),
            save_workspace_root=lambda path: Path(path),
            clear_saved_workspace_root=lambda: False,
        ),
        "pds_core.school_years": SimpleNamespace(
            load_school_year_state=lambda root: None,
        ),
        "pds_core.classes": SimpleNamespace(
            list_class_folders=lambda root, **kwargs: (),
            load_class_roster=lambda root, class_id: None,
        ),
        "pds_core.class_metadata": SimpleNamespace(
            load_class_metadata_for_class=lambda root, class_id: None,
        ),
        "pds_core.standards": SimpleNamespace(
            load_workspace_standards_library=lambda root: None,
        ),
        "pds_core.starter_standards": SimpleNamespace(
            list_starter_standards_packs=lambda: (),
        ),
        "pds_core.academic_period_storage": SimpleNamespace(
            load_current_academic_period_calendar=lambda root, school_year: None,
            get_current_academic_period_calendar_revision=(
                lambda root, school_year: None
            ),
        ),
    }

    def version_lookup(distribution: str) -> str:
        events.append(f"version:{distribution}")
        return core.version

    def importer(name: str) -> object:
        events.append(f"import:{name}")
        return modules[name]

    load_core_classroom_services(
        manifest,
        version_lookup=version_lookup,
        module_importer=importer,
    )

    assert events[0] == f"version:{core.distribution}"
    assert events[1] == "import:pds_core.workspace"
    assert events[2:] == [
        "import:pds_core.school_years",
        "import:pds_core.classes",
        "import:pds_core.class_metadata",
        "import:pds_core.standards",
        "import:pds_core.starter_standards",
        "import:pds_core.academic_period_storage",
    ]


def test_load_services_requires_exact_public_callable() -> None:
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
            load_school_year_state=lambda root: None
        ),
        "pds_core.classes": SimpleNamespace(
            list_class_folders=lambda root, **kwargs: (),
            load_class_roster=lambda root, class_id: None,
        ),
        "pds_core.class_metadata": SimpleNamespace(
            load_class_metadata_for_class=lambda root, class_id: None
        ),
        "pds_core.standards": SimpleNamespace(
            load_workspace_standards_library=lambda root: None
        ),
        "pds_core.starter_standards": SimpleNamespace(),
        "pds_core.academic_period_storage": SimpleNamespace(
            load_current_academic_period_calendar=lambda root, school_year: None,
            get_current_academic_period_calendar_revision=(
                lambda root, school_year: None
            ),
        ),
    }

    with pytest.raises(CoreClassroomServiceError, match="list_starter_standards_packs"):
        load_core_classroom_services(
            manifest,
            version_lookup=lambda _distribution: core.version,
            module_importer=lambda name: modules[name],
        )


def test_assessment_rejects_missing_workspace_without_other_reads(
    tmp_path: Path,
) -> None:
    fake = FakeCore(tmp_path / "missing")
    fake.workspace = FakeWorkspaceStatus(root=fake.root, exists=False, is_dir=False)

    with pytest.raises(ClassroomWorkspaceError, match="pds workspace setup"):
        assess_shared_setup(services=fake.services())

    assert fake.calls == ["workspace.inspect"]
    assert not fake.root.exists()


def test_assessment_accepts_empty_existing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fake = FakeCore(root)

    assessment = assess_shared_setup(services=fake.services())

    assert assessment.workspace_root == root
    assert assessment.active_school_year is None
    assert assessment.classes == ()
    assert assessment.standards_count == 0
    assert assessment.standards_profile_count == 0
    assert assessment.academic_period_calendar is None
    assert assessment.academic_period_revision is None
    assert not any(call.startswith("periods.") for call in fake.calls)


def test_assessment_loads_valid_existing_shared_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    class_dir = root / "classes" / "eng10-p2"
    class_dir.mkdir(parents=True)
    metadata_path = class_dir / "class.json"
    roster_path = class_dir / "roster.csv"
    metadata_path.write_text("{}", encoding="utf-8")
    roster_path.write_text("synthetic", encoding="utf-8")

    fake = FakeCore(root)
    fake.school_year = FakeSchoolYearState(
        active_school_year="2026-2027",
        opened_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    fake.folders = (
        FakeClassFolder(
            class_id="eng10-p2",
            class_dir=class_dir,
            roster_path=roster_path,
            metadata_path=metadata_path,
        ),
    )
    fake.metadata_by_class["eng10-p2"] = FakeClassMetadata(
        class_id="eng10-p2",
        school_year="2026-2027",
        module_details={},
    )
    fake.roster_by_class["eng10-p2"] = FakeRoster(
        class_id="eng10-p2",
        students=(FakeStudent("s001"), FakeStudent("s002")),
    )
    fake.standards = FakeStandardsLibrary(
        standards=(object(), object(), object()),
        profiles=(object(),),
    )
    fake.starter_packs = (
        FakeStarterPack(
            pack_id="example",
            title="Example",
            source="Synthetic",
            grade_bands=("9-10",),
            courses=("English 10",),
            standard_count=3,
            profile_count=1,
        ),
    )
    fake.calendar = FakeCalendar(
        school_year="2026-2027",
        calendar_revision=1,
        periods=(object(), object()),
    )
    fake.revision = 1

    assessment = assess_shared_setup(services=fake.services())

    assert assessment.active_school_year == "2026-2027"
    assert len(assessment.classes) == 1
    assert assessment.classes[0].has_metadata is True
    assert assessment.classes[0].has_roster is True
    assert assessment.classes[0].student_count == 2
    assert assessment.standards_count == 3
    assert assessment.standards_profile_count == 1
    assert assessment.starter_standards_packs[0].pack_id == "example"
    assert assessment.academic_period_revision == 1


def test_assessment_does_not_load_calendar_for_closed_school_year(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fake = FakeCore(root)
    fake.school_year = FakeSchoolYearState(
        active_school_year="2025-2026",
        opened_at=datetime(2025, 8, 20, tzinfo=UTC),
        closed_at=datetime(2026, 6, 30, tzinfo=UTC),
    )

    assessment = assess_shared_setup(services=fake.services())

    assert assessment.active_school_year is None
    assert not any(call.startswith("periods.") for call in fake.calls)


def test_assessment_refuses_malformed_class_metadata(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    class_dir = root / "classes" / "eng10"
    class_dir.mkdir(parents=True)
    metadata_path = class_dir / "class.json"
    metadata_path.write_text("malformed", encoding="utf-8")
    fake = FakeCore(root)
    fake.folders = (
        FakeClassFolder(
            class_id="eng10",
            class_dir=class_dir,
            roster_path=class_dir / "roster.csv",
            metadata_path=metadata_path,
        ),
    )
    fake.fail_area = "metadata:eng10"

    with pytest.raises(ClassroomSetupAssessmentError, match="class metadata"):
        assess_shared_setup(services=fake.services())


def test_assessment_refuses_malformed_roster(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    class_dir = root / "classes" / "eng10"
    class_dir.mkdir(parents=True)
    roster_path = class_dir / "roster.csv"
    roster_path.write_text("malformed", encoding="utf-8")
    fake = FakeCore(root)
    fake.folders = (
        FakeClassFolder(
            class_id="eng10",
            class_dir=class_dir,
            roster_path=roster_path,
            metadata_path=class_dir / "class.json",
        ),
    )
    fake.fail_area = "roster:eng10"

    with pytest.raises(ClassroomSetupAssessmentError, match="roster"):
        assess_shared_setup(services=fake.services())


def test_assessment_refuses_malformed_standards_library(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fake = FakeCore(root)
    fake.fail_area = "standards"

    with pytest.raises(ClassroomSetupAssessmentError, match="standards-library"):
        assess_shared_setup(services=fake.services())


def test_assessment_refuses_academic_period_pointer_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fake = FakeCore(root)
    fake.school_year = FakeSchoolYearState(
        active_school_year="2026-2027",
        opened_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    fake.calendar = FakeCalendar(
        school_year="2026-2027",
        calendar_revision=2,
        periods=(),
    )
    fake.revision = 1

    with pytest.raises(
        ClassroomSetupAssessmentError,
        match="revision pointer disagree",
    ):
        assess_shared_setup(services=fake.services())


def test_assessment_preserves_core_objects_without_copying_sensitive_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    class_dir = root / "classes" / "eng10"
    class_dir.mkdir(parents=True)
    roster_path = class_dir / "roster.csv"
    roster_path.touch()
    fake = FakeCore(root)
    roster = FakeRoster(
        class_id="eng10",
        students=(FakeStudent("opaque-student-id"),),
    )
    fake.folders = (
        FakeClassFolder(
            class_id="eng10",
            class_dir=class_dir,
            roster_path=roster_path,
            metadata_path=class_dir / "class.json",
        ),
    )
    fake.roster_by_class["eng10"] = roster

    assessment = assess_shared_setup(services=fake.services())

    assert assessment.classes[0].roster is roster
    assert assessment.classes[0].student_count == 1


def test_service_dataclass_rejects_no_fake_writes_by_construction(
    tmp_path: Path,
) -> None:
    """The slice-1 service surface intentionally contains readers only."""
    fake = FakeCore(tmp_path)
    services = fake.services()

    assert not hasattr(services, "open_school_year")
    assert not hasattr(services, "ensure_class_folder")
    assert not hasattr(services, "write_class_roster")
    assert not hasattr(services, "install_starter_standards_library")
    assert not hasattr(services, "write_academic_period_calendar")

    cast(object, services)


def test_load_services_matches_installed_qualified_core_public_contract() -> None:
    services = load_core_classroom_services()

    assert callable(services.load_school_year_state)
    assert callable(services.list_class_folders)
    assert callable(services.load_class_metadata_for_class)
    assert callable(services.load_class_roster)
    assert callable(services.load_workspace_standards_library)
    assert callable(services.list_starter_standards_packs)
    assert callable(services.load_current_academic_period_calendar)
    assert callable(services.get_current_academic_period_calendar_revision)
