"""Real Core/Quillan/ScoreForm synthetic handler contract rehearsal.

Requires a separately installed, exact official-wheel environment. Test data
lives only under a caller-provided disposable directory; no teacher workspace
or source file is read. ScoreForm's unissued-sheet refusal is a NEGATIVE test,
not positive scored-page qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from paper_data_suite.returned_paper_installed_wheels import (
    WheelQualificationError,
    qualify_installed_profiles,
)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def _synthetic_png(root: Path, filename: str) -> Path:
    from PIL import Image

    path = root / filename
    Image.new("RGB", (80, 100), "white").save(path, format="PNG")
    return path


def _quillan_request(root: Path) -> Any:
    from pds_core.module_dispatch import RouteDispatchRequest
    from pds_core.rosters import StudentRecord
    from pds_core.route_registrations import write_route_registration
    from pds_core.scan_retention import retain_source_scan
    from quillan.printable_response_persistence import (
        canonical_printable_response_json,
    )
    from quillan.printable_response_records import (
        PrintableResponseRecordSet,
        build_printable_response_record_set,
        transition_printable_response_lifecycle,
    )
    from quillan.printable_response_routes import (
        build_printable_response_page_route,
    )
    from quillan.work_paths import quillan_work_paths

    assignment: dict[str, object] = {
        "schema_version": "2", "module": "quillan",
        "record_type": "assignment", "assignment_id": "synthetic_essay",
        "title": "Synthetic qualification", "class_ids": ["synthetic_class"],
        "writing_type": "literary_analysis", "student_prompt": "Synthetic",
        "standards_profile_id": "synthetic_profile",
        "focus_standard_ids": ["W.1"],
        "review_unit": {
            "type": "paragraph", "singular_label": "paragraph",
            "plural_label": "paragraphs",
        },
        "rating_scale": {
            "scale_id": "synthetic_scale",
            "levels": [{
                "value": 1, "label": "Meets", "description": "Meets",
            }],
        },
        "basic_requirements": {},
        "minimum_requirement_policy": {
            "allow_return_without_full_review": True,
        },
        "created_at": "2026-07-19T18:00:00+00:00",
        "updated_at": "2026-07-19T18:00:00+00:00",
        "module_details": {},
    }
    student = StudentRecord(
        "synthetic_class", "synthetic_student", "Student", "Sample", "1", {}
    )
    records = build_printable_response_record_set(
        "synthetic_class", assignment, student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="class_packet_pdf", reason="initial",
        pages_per_student=1, issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,), class_label="Synthetic Class",
        clock=lambda: datetime(2026, 7, 19, 18, 30, tzinfo=timezone.utc),
    )
    lifecycle = transition_printable_response_lifecycle(
        records.issuance.lifecycle, new_status="issued",
        timestamp="2026-07-20T00:00:00+00:00",
    )
    records = PrintableResponseRecordSet(
        replace(records.issuance, lifecycle=lifecycle), records.pages
    )
    paths = quillan_work_paths(
        root, records.issuance.class_id, records.issuance.assignment_id
    )
    paths.response_page_records_dir.mkdir(parents=True, exist_ok=True)
    paths.response_page_issuances_dir.mkdir(parents=True, exist_ok=True)
    for page in records.pages:
        (paths.response_page_records_dir / f"{page.page_id}.json").write_bytes(
            canonical_printable_response_json(page.to_mapping())
        )
    (paths.response_page_issuances_dir / (
        records.issuance.issuance_id + ".json"
    )).write_bytes(
        canonical_printable_response_json(records.issuance.to_mapping())
    )
    route = build_printable_response_page_route(
        records.pages[0], "rt_" + "5" * 32
    )
    write_route_registration(root, route.registration)
    retained = retain_source_scan(root, _synthetic_png(root, "quillan.png"))
    return RouteDispatchRequest(route.locator, retained, 1)


def _scoreform_unissued_request(root: Path) -> Any:
    from pds_core.module_dispatch import RouteDispatchRequest
    from pds_core.scan_retention import retain_source_scan
    from scoreform.answer_sheet_persistence import write_answer_sheet_record_set
    from scoreform.answer_sheet_records import build_answer_sheet_record_set
    from scoreform.answer_sheet_routes import (
        build_answer_sheet_page_route,
        persist_answer_sheet_route_set,
    )
    from scoreform.folders import setup_assignment_folder

    assignment: dict[str, Any] = {
        "assignment_id": "synthetic_quiz", "title": "Synthetic",
        "question_count": 1, "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1", "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    student: dict[str, str] = {
        "class_id": "synthetic_class", "student_id": "student01",
        "last_name": "Sample", "first_name": "Student", "period": "1",
    }
    setup = setup_assignment_folder(
        {"class_id": "synthetic_class", "students": [student]},
        assignment, workspace_root=root,
    )
    if setup is None:
        raise WheelQualificationError("ScoreForm fixture setup unavailable")
    paths = setup["paths"]
    records = build_answer_sheet_record_set(
        "synthetic_class", assignment, student,
        generation_id="gen_" + "6" * 32,
        artifact_id="art_" + "7" * 32,
        output_kind="individual_pdf", reason="initial",
        issuance_id="iss_" + "8" * 32,
        page_ids=("pg_" + "9" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    write_answer_sheet_record_set(root, paths.work_ref, records)
    route = build_answer_sheet_page_route(
        paths.work_ref, records.pages[0], route_id="rt_" + "a" * 32
    )
    persist_answer_sheet_route_set(root, paths.work_ref, records, (route,))
    retained = retain_source_scan(root, _synthetic_png(root, "scoreform.png"))
    return RouteDispatchRequest(route.locator, retained, 1)


def qualify_real_producer_handlers(root: Path) -> tuple[str, str]:
    """Exercise actual two installed handlers only on disposable synthetic data."""
    from pds_core.module_dispatch import (
        ModuleRouteHandlingError,
        RouteDispatchFailure,
        RouteDispatchSuccess,
        dispatch_routes,
    )
    from pds_core.module_profiles import build_module_registry

    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or root.name != "suite18_synthetic_workspace"
        or root.is_symlink()
        or not root.is_dir()
        or not root.resolve(strict=True).is_relative_to(
            Path(gettempdir()).resolve(strict=True)
        )
        or any(root.iterdir())
    ):
        raise WheelQualificationError("isolated empty temp workspace required")
    if qualify_installed_profiles() != ("quillan", "scoreform"):
        raise WheelQualificationError("exact installed profile pair unavailable")
    registry = build_module_registry(discover_installed=True)
    quillan = _quillan_request(root)
    scoreform = _scoreform_unissued_request(root)
    before = _snapshot(root)
    outcomes = dispatch_routes(root, registry, (quillan, scoreform))
    after = _snapshot(root)
    if len(outcomes) != 2 or before != after:
        raise WheelQualificationError("dispatch changed synthetic source files")
    first, second = outcomes
    if (
        not isinstance(first, RouteDispatchSuccess)
        or first.request != quillan
        or first.profile.module_id != "quillan"
        or getattr(first.module_result, "route_id", None)
        != quillan.locator.route_id
    ):
        raise WheelQualificationError("Quillan handler success not established")
    if (
        not isinstance(second, RouteDispatchFailure)
        or second.request != scoreform
        or not isinstance(second.error, ModuleRouteHandlingError)
    ):
        raise WheelQualificationError("ScoreForm unissued refusal not established")
    return "handler_returned", "unissued_refused"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-workspace", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        quillan, scoreform = qualify_real_producer_handlers(
            arguments.synthetic_workspace
        )
    except (Exception, KeyboardInterrupt):
        print("SUITE18_REAL_PRODUCER_REHEARSAL_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps({
        "contract": "issue18-slice6a-1",
        "quillan": quillan,
        "scoreform": scoreform,
        "core_dispatch_routes_used": True,
        "actual_published_producer_handlers_called": 2,
        "positive_scoreform_scoring_qualified": False,
        "native_mixed_paper_qualified": False,
        "live_teacher_pilot_qualified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
