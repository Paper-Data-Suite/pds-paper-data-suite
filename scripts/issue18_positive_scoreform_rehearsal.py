"""Isolated official-wheel positive ScoreForm scoring qualification for Suite #18.

This is NOT a teacher command, replay mechanism, or production scoring pathway.
It accepts an empty, disposable workspace beneath the OS temporary directory.
Source PNG, Core route, issued ScoreForm records, and all answers are synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from paper_data_suite.returned_paper_installed_wheels import (
    WheelQualificationError,
    qualify_installed_profiles,
)

_EXPECTED: tuple[str, ...] = ("A", "B", "C", "D")


def _safe_empty_workspace(root: Path) -> bool:
    """Refuse existing files, teacher workspaces, links, and remote roots."""
    try:
        temp = Path(gettempdir()).resolve(strict=True)
        return (
            isinstance(root, Path)
            and root.is_absolute()
            and root.name == "suite18_synthetic_workspace"
            and not root.is_symlink()
            and root.is_dir()
            and root.resolve(strict=True).is_relative_to(temp)
            and not any(root.iterdir())
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _snapshot(root: Path) -> dict[str, str]:
    """Keep fingerprints private; never print page or record contents."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _draw_marked_sheet(path: Path) -> None:
    """Match ScoreForm 0.13.0's public production OMR geometry exactly."""
    import cv2
    import numpy as np
    from scoreform.config import (
        BOX_SIZE,
        BOX_START_X,
        BOX_STEP_X,
        CORNER_SIZE,
        CORNERS,
        IMG_HEIGHT,
        IMG_WIDTH,
        Q_START_Y,
        Q_STEP_Y,
    )

    image = np.full((IMG_HEIGHT, IMG_WIDTH, 3), 255, dtype=np.uint8)
    for x, y in CORNERS:
        cv2.rectangle(
            image, (x, y), (x + CORNER_SIZE, y + CORNER_SIZE),
            (0, 0, 0), -1,
        )
    for number, selected in enumerate(_EXPECTED):
        y = Q_START_Y + number * Q_STEP_Y
        for index, letter in enumerate(_EXPECTED):
            x = BOX_START_X + index * BOX_STEP_X
            cv2.rectangle(
                image, (x, y), (x + BOX_SIZE, y + BOX_SIZE),
                (0, 0, 0), 2,
            )
            if letter == selected:
                cv2.rectangle(
                    image, (x + 6, y + 6),
                    (x + BOX_SIZE - 6, y + BOX_SIZE - 6),
                    (0, 0, 0), -1,
                )
    if not cv2.imwrite(str(path), image):
        raise WheelQualificationError("synthetic OMR PNG could not be created")


def _issued_request(root: Path) -> Any:
    """Create authentic producer-owned issued records and one Core custody event."""
    from pds_core.module_dispatch import RouteDispatchRequest
    from pds_core.scan_retention import retain_source_scan
    from scoreform.answer_sheet_persistence import (
        transition_answer_sheet_issuance,
        write_answer_sheet_record_set,
    )
    from scoreform.answer_sheet_records import build_answer_sheet_record_set
    from scoreform.answer_sheet_routes import (
        build_answer_sheet_page_route,
        persist_answer_sheet_route_set,
    )
    from scoreform.folders import setup_assignment_folder

    assignment: dict[str, Any] = {
        "assignment_id": "synthetic_quiz", "title": "Synthetic Scoring",
        "question_count": 4, "choices": list(_EXPECTED),
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(i): answer for i, answer in enumerate(
            _EXPECTED, start=1
        )},
        "standards": {str(i): [] for i in range(1, 5)},
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
    work = setup["paths"].work_ref
    records = build_answer_sheet_record_set(
        "synthetic_class", assignment, student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf", reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    write_answer_sheet_record_set(root, work, records)
    route = build_answer_sheet_page_route(
        work, records.pages[0], route_id="rt_" + "5" * 32
    )
    persist_answer_sheet_route_set(root, work, records, (route,))
    issued = transition_answer_sheet_issuance(
        root, work, records.issuance.issuance_id,
        expected_revision=1, new_status="issued",
        timestamp="2026-01-01T00:00:01+00:00",
    )
    if issued.lifecycle.status != "issued" or issued.lifecycle.revision != 2:
        raise WheelQualificationError("ScoreForm issuance was not issued")
    source = root / "scoreform_issued_synthetic.png"
    _draw_marked_sheet(source)
    retained = retain_source_scan(root, source)
    return RouteDispatchRequest(route.locator, retained, 1)


def _exact_answers(
    answers: tuple[tuple[int, str, bool], ...],
    expected: tuple[str, ...] = _EXPECTED,
) -> bool:
    """Reject a partial, wrong-order, ambiguous, or falsely marked OMR result."""
    return (
        type(answers) is tuple
        and len(answers) == len(expected)
        and all(
            type(item) is tuple
            and len(item) == 3
            and type(item[0]) is int
            and item[0] == number
            and type(item[1]) is str
            and item[1] == letter
            and type(item[2]) is bool
            and item[2] is True
            for number, (item, letter) in enumerate(
                zip(answers, expected, strict=True), start=1
            )
        )
    )


def qualify_positive_scoreform(root: Path) -> None:
    """Require actual Core success and a strictly verified producer-owned score."""
    from pds_core.module_dispatch import RouteDispatchSuccess, dispatch_routes
    from pds_core.module_profiles import build_module_registry
    from scoreform.page_scoring import (
        ScoreFormPageDispatchResult,
        validate_page_dispatch_result,
    )
    from scoreform.work_paths import scoreform_work_paths

    if not _safe_empty_workspace(root):
        raise WheelQualificationError("empty isolated temp workspace required")
    if qualify_installed_profiles() != ("quillan", "scoreform"):
        raise WheelQualificationError("exact installed profile pair unavailable")
    request = _issued_request(root)
    before = _snapshot(root)
    registry = build_module_registry(discover_installed=True)
    outcomes = dispatch_routes(root, registry, (request,))
    after = _snapshot(root)
    if len(outcomes) != 1 or not isinstance(outcomes[0], RouteDispatchSuccess):
        raise WheelQualificationError("issued ScoreForm Core dispatch did not succeed")
    outcome = outcomes[0]
    result = outcome.module_result
    if (
        outcome.request != request
        or outcome.profile.module_id != "scoreform"
        or not isinstance(result, ScoreFormPageDispatchResult)
    ):
        raise WheelQualificationError("unexpected positive ScoreForm return type")
    validate_page_dispatch_result(result, valid_choices=_EXPECTED)
    answers = tuple(
        (answer.question_number, answer.selected_answer, answer.correct)
        for answer in result.answers
    )
    if (
        result.route_id != request.locator.route_id
        or result.source_scan_id != request.retained_source.source_scan_id
        or result.source_page_number != 1
        or result.retained_source_relative_path
        != request.retained_source.retained_source_relative_path
        or result.source_sha256 != request.retained_source.source_sha256
        or result.score != 4
        or result.total_points != 4
        or not _exact_answers(answers)
    ):
        raise WheelQualificationError("ScoreForm scored values/provenance differ")
    # A positive page may generate module-owned diagnostics, but cannot mutate
    # previously issued records, the Core registration, or retained-source bytes.
    if any(after.get(name) != digest for name, digest in before.items()):
        raise WheelQualificationError("dispatch altered immutable synthetic input")
    debug = scoreform_work_paths(
        root, request.locator.class_id, request.locator.work_id
    ).debug_dir.relative_to(root).as_posix().rstrip("/") + "/"
    new_paths = set(after) - set(before)
    if any(not path.startswith(debug) for path in new_paths):
        raise WheelQualificationError("dispatch wrote outside producer debug area")
    for diagnostic in result.diagnostic_paths:
        p = Path(diagnostic)
        if p.is_symlink() or not p.is_file():
            raise WheelQualificationError("ScoreForm diagnostic path is invalid")
        try:
            p.resolve(strict=True).relative_to(
                (root / debug).resolve(strict=True)
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise WheelQualificationError(
                "ScoreForm diagnostic escaped producer-owned debug"
            ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-workspace", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        qualify_positive_scoreform(arguments.synthetic_workspace)
    except (Exception, KeyboardInterrupt):
        print("SUITE18_POSITIVE_SCOREFORM_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps({
        "contract": "issue18-slice6b1-1",
        "official_installed_handlers": ("quillan", "scoreform"),
        "core_dispatch_routes_used": True,
        "scoreform": "issued_page_scored",
        "exact_four_answers": True,
        "retained_provenance_checked": True,
        "native_mixed_pdf_qualified": False,
        "teacher_pilot_qualified": False,
        "suite_release_trust_qualified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
