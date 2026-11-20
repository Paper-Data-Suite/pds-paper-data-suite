"""#19E4A: page-complete read-only result rendering from actual Core records."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_issue18_slice4_ordered_dispatch import (
    _approve,
    _case,
    _code,
    _dispatch_success,
    _registry,
)
from test_issue18_slice5_core_review import (
    _failure_dispatch,
    _run,
)

from paper_data_suite.returned_paper_core_review import (
    CoreReviewResultV1,
    execute_with_core_review,
)
from paper_data_suite.returned_paper_ordered_dispatch import (
    count_ordered_dispatch_groups,
)
from paper_data_suite.returned_paper_readonly_decode import DecodedPage
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_dispatch_action import (
    TeacherDispatchActionResultV1,
    render_teacher_dispatch_action,
)
from paper_data_suite.returned_paper_teacher_results import (
    TeacherPaperResultsError,
    _safe_identifier,
    render_core_paper_page_detail,
    render_core_paper_results,
)


def test_real_core_completed_reports_each_page_and_no_grade_claim(
    tmp_path: Path,
) -> None:
    core = _run(tmp_path)
    detail = render_core_paper_results(core)
    assert "Core run: completed." in detail
    assert "Physical pages accounted for: 2." in detail
    assert "Core handler attempts: 2." in detail
    assert detail.count("  Page ") == 2
    assert "Producer handler returned; evidence not confirmed: 2" in detail
    assert "scoreform / english12_p4 / essay" in detail
    assert "quillan / english12_p4 / essay" in detail
    assert "No grade publication is established" in detail
    assert str(tmp_path) not in detail


def test_one_based_page_drilldown_cannot_invent_page(
    tmp_path: Path,
) -> None:
    core = _run(tmp_path)
    text = render_core_paper_page_detail(core, 1, 2)
    assert text.startswith("Source 1\n  Page 2:")
    assert "Core-parsed locator: quillan/english12_p4/essay" in text
    for source, page in ((0, 1), (1, 0), (2, 1), (1, 99), (True, 1)):
        with pytest.raises(TeacherPaperResultsError):
            render_core_paper_page_detail(core, source, page)


def test_unselected_page_is_still_accounted_for(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _case(
        tmp_path,
        ((DecodedPage((_code("scoreform"),)), DecodedPage()),),
        selected=((1, 1),),
    )
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    core = execute_with_core_review(
        batch,
        approve=_approve,
        decode=decode,
        registry_factory=_registry,
        dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    text = render_core_paper_results(core)
    assert "Physical pages accounted for: 2." in text
    assert "Not selected: 1" in text
    assert "  Page 2: Not selected." in text
    assert "Next: No action requested" in text
    assert "Core handler attempts: 1." in text


def test_unresolved_qr_is_never_given_invented_route(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _case(
        tmp_path,
        ((DecodedPage((_code("scoreform"),)), DecodedPage()),),
    )
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    core = execute_with_core_review(
        batch,
        approve=_approve,
        decode=decode,
        registry_factory=_registry,
        dispatcher=_dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
    )
    text = render_core_paper_page_detail(core, 1, 2)
    assert "QR unresolved" in text
    assert "Core-parsed locator:" not in text
    assert "Inspect verified Core failure" in text or "Inspect the source page" in text
    grouped = count_ordered_dispatch_groups(core.execution)
    assert any(row.module_id is None for row in grouped)
    assert "unknown / unknown / unknown" in render_core_paper_results(core)


def test_actual_recorded_core_failure_has_only_verified_reference(
    tmp_path: Path,
) -> None:
    from pds_core.route_registrations import RouteRegistrationNotFoundError

    core = _run(
        tmp_path,
        dispatcher=_failure_dispatch(
            RouteRegistrationNotFoundError("SECRET STUDENT IDENTIFIER")
        ),
    )
    text = render_core_paper_results(core)
    assert "Verified Core failure record" in text
    assert "Core failure ID: failure_" in text
    assert "SECRET STUDENT" not in text
    assert "Core failure record is NOT a resolution" in text
    assert str(tmp_path) not in text


def test_review_category_with_unsafe_content_is_not_echoed(
    tmp_path: Path,
) -> None:
    from pds_core.route_registrations import RouteRegistrationNotFoundError

    core = _run(
        tmp_path,
        dispatcher=_failure_dispatch(RouteRegistrationNotFoundError("missing")),
    )
    row = core.pages[0]
    assert row.review_state == "recorded"
    changed = replace(row, failure_category="PRIVATE\nstudent name")
    altered = CoreReviewResultV1(core.execution, (changed, *core.pages[1:]))
    text = render_core_paper_results(altered)
    assert "PRIVATE" not in text
    assert "student name" not in text
    assert "Core failure ID: failure_" in text


def test_rendering_reads_no_files_and_writes_no_results(
    tmp_path: Path,
) -> None:
    core = _run(tmp_path)
    before = tuple(sorted(str(p) for p in tmp_path.rglob("*")))
    assert render_core_paper_results(core)
    assert render_core_paper_page_detail(core, 1, 1)
    after = tuple(sorted(str(p) for p in tmp_path.rglob("*")))
    assert after == before


def test_existing_bridge_summary_now_includes_page_detail(
    tmp_path: Path,
) -> None:
    core = _run(tmp_path)
    bridge = TeacherDispatchActionResultV1("completed", core)
    text = render_teacher_dispatch_action(bridge)
    assert "Action status: completed" in text
    assert "Core attempted physical pages: 2." in text
    assert "Every physical page (including unselected pages):" in text
    assert "  Page 1:" in text and "  Page 2:" in text
    assert "No grade publication is established" in text


def test_refused_bridge_does_not_invent_core_page_rows() -> None:
    result = TeacherDispatchActionResultV1("admission_refused")
    text = render_teacher_dispatch_action(result)
    assert "No verified Core dispatch result" in text
    assert "Every physical page" not in text


def test_untyped_and_leaking_identifiers_are_refused_or_withheld() -> None:
    with pytest.raises(TeacherPaperResultsError):
        render_core_paper_results(object())  # type: ignore[arg-type]
    with pytest.raises(TeacherPaperResultsError):
        render_core_paper_page_detail(object(), 1, 1)  # type: ignore[arg-type]
    assert _safe_identifier("class\nPRIVATE") == "withheld"
    assert _safe_identifier("scoreform") == "scoreform"
    assert _safe_identifier(None) == "unknown"


def test_only_read_only_core_public_reporting_seam() -> None:
    source = (Path(__file__).parents[1] /
              "paper_data_suite/returned_paper_teacher_results.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "dispatch_routes(", "retain_source_scan(", "write_route_registration(",
        "execute_with_core_review(", "prepare_retained_pds2_requests(",
        "qualified_modules=", "open(", "write_text(", "write_bytes(",
    ):
        assert forbidden not in source
