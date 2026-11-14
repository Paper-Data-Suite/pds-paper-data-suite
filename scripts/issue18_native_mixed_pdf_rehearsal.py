"""Native two-page PDS2 PDF, Core custody and real dispatch qualification.

This is an explicit, disposable **synthetic-only** acceptance harness.
It is not a teacher command, a replay mechanism or publication authority.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from issue18_positive_scoreform_rehearsal import (
    _EXPECTED,
    _draw_marked_sheet,
    _exact_answers,
    _safe_empty_workspace,
    _snapshot,
)

from paper_data_suite.returned_paper_authorized_retention import (
    RetentionDecisionV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_installed_wheels import (
    WheelQualificationError,
    qualify_installed_profiles,
)
from paper_data_suite.returned_paper_ordered_dispatch import (
    DispatchDecisionV1,
    execute_prepared_paper_batch,
)
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    build_processing_plan,
    count_processing_outcomes,
)
from paper_data_suite.returned_paper_readonly_decode import (
    observe_selected_sources,
)
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)

_EXPECTED_MODULES = ("scoreform", "quillan")


def _exact_preview(observations: object) -> bool:
    """Require distinct, ordered physical pages, not mere QR presence."""
    if not isinstance(observations, tuple) or len(observations) != 1:
        return False
    source = observations[0]
    if not isinstance(source, SourcePreview):
        return False
    return (
        source.status == "observed"
        and len(source.pages) == 2
        and source.sha256_advisory is not None
        and all(
            page.page_number == position
            and page.status == "candidate_unverified"
            and page.candidate_module_id == module
            for position, (page, module) in enumerate(
                zip(source.pages, _EXPECTED_MODULES, strict=True), start=1
            )
        )
    )


def _make_scoreform_route(root: Path) -> Any:
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
        "assignment_id": "synthetic_quiz", "title": "Synthetic ScoreForm",
        "question_count": 4, "choices": list(_EXPECTED),
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(i): choice for i, choice in enumerate(
            _EXPECTED, start=1
        )},
        "standards": {str(i): [] for i in range(1, 5)},
    }
    student: dict[str, str] = {
        "class_id": "synthetic_class", "student_id": "student01",
        "last_name": "Sample", "first_name": "Student", "period": "1",
    }
    with redirect_stdout(io.StringIO()):
        setup = setup_assignment_folder(
            {"class_id": "synthetic_class", "students": [student]},
            assignment, workspace_root=root,
        )
    if setup is None:
        raise WheelQualificationError("ScoreForm fixture setup refused")
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
        raise WheelQualificationError("ScoreForm issuance not authorized")
    return route.locator


def _make_quillan_route(root: Path) -> Any:
    from pds_core.rosters import StudentRecord
    from pds_core.route_registrations import write_route_registration
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
        "title": "Synthetic writing", "class_ids": ["synthetic_class"],
        "writing_type": "literary_analysis", "student_prompt": "Synthetic",
        "standards_profile_id": "synthetic_profile",
        "focus_standard_ids": ["W.1"],
        "review_unit": {
            "type": "paragraph", "singular_label": "paragraph",
            "plural_label": "paragraphs",
        },
        "rating_scale": {
            "scale_id": "synthetic_scale",
            "levels": [{"value": 1, "label": "Meets", "description": "Meets"}],
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
        "synthetic_class", "student01", "Student", "Sample", "1", {}
    )
    records = build_printable_response_record_set(
        "synthetic_class", assignment, student,
        generation_id="gen_" + "a" * 32,
        artifact_id="art_" + "b" * 32,
        output_kind="class_packet_pdf", reason="initial",
        pages_per_student=1, issuance_id="iss_" + "c" * 32,
        page_ids=("pg_" + "d" * 32,), class_label="Synthetic Class",
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
        records.pages[0], "rt_" + "e" * 32
    )
    write_route_registration(root, route.registration)
    return route.locator


def _create_mixed_pdf(
    destination: Path, image_path: Path, locators: tuple[Any, Any]
) -> None:
    """QRs remain outside OMR corners/answer boxes at 612x792 PDF scale."""
    import qrcode
    from pds_core.pds2 import serialize_pds2_payload
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    pdf = Canvas(str(destination), pagesize=(612, 792), pageCompression=1)
    for number, locator in enumerate(locators, 1):
        if number == 1:
            pdf.drawImage(
                str(image_path), 0, 0, width=612, height=792,
                preserveAspectRatio=False,
            )
        else:
            pdf.setFont("Helvetica", 12)
            pdf.drawString(48, 735, "Synthetic Quillan response page")
            pdf.drawString(48, 710, "No real student work is present.")
        payload = serialize_pds2_payload(locator)
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=12, border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        pdf.drawImage(
            ImageReader(qr_image.get_image().convert("RGB")),
            450, 550, width=125, height=125,
        )
        pdf.showPage()
    pdf.save()
    if (
        destination.stat().st_size < 100
        or destination.stat().st_size > 24 * 1024 * 1024
        or not destination.read_bytes().startswith(b"%PDF-")
    ):
        raise WheelQualificationError("bounded synthetic PDF was not generated")


def _authorize_retention(review: Any) -> RetentionDecisionV1:
    return RetentionDecisionV1("approve", review.plan_digest, review.challenge)


def _cancel_retention(review: Any) -> RetentionDecisionV1:
    return RetentionDecisionV1("cancel", review.plan_digest, review.challenge)


def _authorize_dispatch(review: Any) -> DispatchDecisionV1:
    if not review.producer_handlers_may_write:
        raise WheelQualificationError("write disclosure absent")
    return DispatchDecisionV1("approve", review.plan_digest, review.challenge)


def _cancel_dispatch(review: Any) -> DispatchDecisionV1:
    return DispatchDecisionV1("cancel", review.plan_digest, review.challenge)


def _verify_dispatch_results(
    results: tuple[Any, ...], requests: tuple[Any, ...]
) -> None:
    from pds_core.module_dispatch import RouteDispatchSuccess
    from scoreform.page_scoring import (
        ScoreFormPageDispatchResult,
        validate_page_dispatch_result,
    )
    if len(results) != 2 or len(requests) != 2:
        raise WheelQualificationError("native handler result count mismatch")
    if any(
        not isinstance(outcome, RouteDispatchSuccess)
        or outcome.request != request
        or outcome.profile.module_id != module
        for outcome, request, module in zip(
            results, requests, _EXPECTED_MODULES, strict=True
        )
    ):
        raise WheelQualificationError("native dispatched pages were not successful")
    scored = results[0].module_result
    if not isinstance(scored, ScoreFormPageDispatchResult):
        raise WheelQualificationError("ScoreForm native result type differs")
    validate_page_dispatch_result(scored, valid_choices=_EXPECTED)
    actual = tuple(
        (answer.question_number, answer.selected_answer, answer.correct)
        for answer in scored.answers
    )
    if (
        scored.score != 4 or scored.total_points != 4
        or not _exact_answers(actual)
        or scored.source_page_number != 1
        or scored.source_scan_id != requests[0].retained_source.source_scan_id
        or scored.source_sha256 != requests[0].retained_source.source_sha256
        or scored.retained_source_relative_path
        != requests[0].retained_source.retained_source_relative_path
        or scored.route_id != requests[0].locator.route_id
    ):
        raise WheelQualificationError("native ScoreForm values/provenance differ")
    if (
        getattr(results[1].module_result, "route_id", None)
        != requests[1].locator.route_id
    ):
        raise WheelQualificationError("Quillan native result identity differs")


def qualify_native_mixed_pdf(root: Path) -> None:
    """One genuine native decode and exactly one dispatch for each approved page."""
    from pds_core.module_dispatch import dispatch_routes
    from scoreform.work_paths import scoreform_work_paths

    if not _safe_empty_workspace(root):
        raise WheelQualificationError("an empty isolated temp workspace is required")
    if qualify_installed_profiles() != ("quillan", "scoreform"):
        raise WheelQualificationError("installed producer profile pair differs")
    scoreform = _make_scoreform_route(root)
    quillan = _make_quillan_route(root)
    original = root.parent / "suite18_native_mixed_synthetic.pdf"
    if original.exists() or original.is_symlink():
        raise WheelQualificationError("synthetic PDF destination already exists")
    image = root / "omr_synthetic.png"
    _draw_marked_sheet(image)
    _create_mixed_pdf(original, image, (scoreform, quillan))
    pdf_digest = hashlib.sha256(original.read_bytes()).hexdigest()

    observations = observe_selected_sources((original,))
    if not _exact_preview(observations):
        raise WheelQualificationError("native QR observation/order differs")
    plan = build_processing_plan(
        root, (original,), IntakePreview(observations, ()),
        ((1, 1), (1, 2)),
    )
    before = _snapshot(root)
    cancelled = authorize_and_retain_sources(plan, approve=_cancel_retention)
    if (
        cancelled.status != "cancelled" or cancelled.approved
        or _snapshot(root) != before
    ):
        raise WheelQualificationError("cancel before retention wrote files")
    retained = authorize_and_retain_sources(plan, approve=_authorize_retention)
    if retained.status != "retained" or not retained.approved:
        raise WheelQualificationError("explicit Core retention was not completed")
    source_row = retained.report.sources[0]
    receipt = source_row.retained_source
    if (
        receipt is None
        or receipt.source_sha256 != pdf_digest
        or receipt.retained_source_path.read_bytes() != original.read_bytes()
        or not receipt.retained_source_path.is_file()
    ):
        raise WheelQualificationError("one original PDF was not retained intact")
    retained_files = tuple((root / "scans" / "source").rglob("*.pdf"))
    if len(retained_files) != 1 or retained_files[0] != receipt.retained_source_path:
        raise WheelQualificationError("retention produced multiple PDF copies")
    batch = prepare_retained_pds2_requests(retained)
    if (
        batch.status != "ready" or len(batch.candidates) != 2
        or tuple(candidate.page_number for candidate in batch.candidates)
        != (1, 2)
        or tuple(candidate.request.locator for candidate in batch.candidates)
        != (scoreform, quillan)
        or any(
            candidate.request.retained_source != receipt
            for candidate in batch.candidates
        )
    ):
        raise WheelQualificationError("retained PDS2 route/page identity differs")
    before_dispatch = _snapshot(root)
    cancelled_dispatch = execute_prepared_paper_batch(
        batch, approve=_cancel_dispatch,
        qualified_modules=frozenset(_EXPECTED_MODULES),
    )
    if (
        cancelled_dispatch.status != "cancelled"
        or cancelled_dispatch.attempted_pages != 0
        or _snapshot(root) != before_dispatch
    ):
        raise WheelQualificationError("cancel before dispatch wrote producer state")

    captured: list[Any] = []

    def capture_dispatch(workspace: Path, registry: Any, requests: Any) -> Any:
        # Qualification-only passive observation; Core actually executes once.
        outcomes = dispatch_routes(workspace, registry, requests)
        captured.extend(outcomes)
        return outcomes

    with redirect_stdout(io.StringIO()):
        result = execute_prepared_paper_batch(
            batch, approve=_authorize_dispatch, dispatcher=capture_dispatch,
            qualified_modules=frozenset(_EXPECTED_MODULES),
        )
    if (
        result.status != "completed"
        or not result.approved or result.attempted_pages != 2
        or count_processing_outcomes(result.report)
        != (("handler_returned", 2),)
    ):
        raise WheelQualificationError("ordered Core dispatch did not complete")
    _verify_dispatch_results(tuple(captured), tuple(
        candidate.request for candidate in batch.candidates
    ))
    after = _snapshot(root)
    if any(after.get(path) != digest for path, digest in before_dispatch.items()):
        raise WheelQualificationError("native dispatch modified prior records")
    debug = scoreform_work_paths(
        root, scoreform.class_id, scoreform.work_id
    ).debug_dir.relative_to(root).as_posix().rstrip("/") + "/"
    if any(
        not path.startswith(debug)
        for path in set(after).difference(before_dispatch)
    ):
        raise WheelQualificationError("native dispatch wrote outside producer debug")
    if hashlib.sha256(original.read_bytes()).hexdigest() != pdf_digest:
        raise WheelQualificationError("original synthetic PDF was mutated")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        qualify_native_mixed_pdf(args.synthetic_workspace)
    except (Exception, KeyboardInterrupt) as error:
        # No absolute path, raw QR, producer data or arbitrary exception body.
        print(
            "SUITE18_NATIVE_MIXED_PDF_REFUSED:" + type(error).__name__,
            file=sys.stderr,
        )
        return 2
    print(json.dumps({
        "contract": "issue18-slice6b2-1",
        "native_pdf_pages": 2,
        "ordered_modules": list(_EXPECTED_MODULES),
        "one_core_retention_event": True,
        "cancel_without_write_qualified": True,
        "core_dispatch_pages": 2,
        "scoreform_issued_omr": "4/4",
        "quillan": "handler_returned",
        "actual_pdfium_zxing_decoding": True,
        "teacher_scanner_qualified": False,
        "suite_release_trust_qualified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
