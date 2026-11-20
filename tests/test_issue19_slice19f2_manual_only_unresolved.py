"""#19F2: unresolved-only Core-retained pages stay manual, not v2 failures."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite import returned_paper_teacher_dispatch_action as action
from paper_data_suite import returned_paper_teacher_preparation as preparation
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_dispatch_action import (
    run_teacher_retained_paper_dispatch,
)
from paper_data_suite.returned_paper_teacher_dispatch_menu import (
    run_post_retention_teacher_menu,
)
from paper_data_suite.returned_paper_teacher_preparation import (
    TeacherPreparationReviewError,
    render_manual_only_followup,
    render_retained_request_review,
    review_core_retained_requests,
)

_slice4 = import_module("test_issue18_slice4_ordered_dispatch")
_actiontests = import_module("test_issue19_slice19e3b2_teacher_dispatch_action")


def _unroutable(root: Path, *, selected=None):
    # A missing QR, an invalid foreign code and an ambiguous QR are all
    # nonroutes. These strings may never appear in teacher-facing output.
    pages = ((
        _slice4.DecodedPage(),
        _slice4.DecodedPage(("PRIVATE_STUDENT_NAME_NEVER_DISPLAY",)),
        _slice4.DecodedPage((
            _slice4._code("scoreform", "route_001"),
            _slice4._code("quillan", "route_002"),
        )),
    ),)
    return _slice4._case(root, pages, selected=selected)


def test_manual_followup_accounts_for_every_selected_physical_page(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _unroutable(tmp_path)
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    assert batch.status == "no_dispatchable_pages"
    assert batch.candidates == ()
    text = render_manual_only_followup(batch)
    for number in (1, 2, 3):
        assert f"Source 1, page {number}: QR unresolved" in text
    assert "Selected unresolved physical pages: 3" in text
    assert "Unselected physical pages: 0" in text
    assert "DEFER is unavailable" in text
    assert "NO Core dispatch result" in text
    assert "PRIVATE_STUDENT_NAME" not in text
    assert "PDS2|" not in text
    assert str(tmp_path) not in text
    assert "failure_" not in text


def test_nonselected_pages_remain_visible_as_nonprocessed(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _unroutable(tmp_path, selected=((1, 1),))
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    text = render_manual_only_followup(batch)
    assert "Selected unresolved physical pages: 1" in text
    assert "Unselected physical pages: 2 (not processed)" in text
    assert "Source 1, page 1" in text
    assert "Source 1, page 2" not in text
    assert "Source 1, page 3" not in text


def test_readonly_retained_review_includes_manual_instructions(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _unroutable(tmp_path)
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    view = render_retained_request_review(batch)
    assert "No selected page produced a valid Core route request" in view
    assert "Manual-only follow-up" in view
    assert "Source 1, page 3" in view
    assert "No verified Core failure ID is present" in view
    assert "Prepared typed Core requests: 0" in view
    assert "Core failure ID: failure_" not in view
    inspected = review_core_retained_requests(
        retained,
        prepare=lambda _: prepare_retained_pds2_requests(
            retained, decode=decode,
        ),
    )
    assert inspected == view


def test_v_menu_review_without_wheelhouse_never_invokes_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained, decode, _ = _unroutable(tmp_path)
    # The preparation function binds its default decoder at definition time.
    monkeypatch.setattr(
        preparation, "review_core_retained_requests",
        lambda receipt: review_core_retained_requests(
            receipt,
            prepare=lambda item: prepare_retained_pds2_requests(
                item, decode=decode,
            ),
        ),
    )
    monkeypatch.setattr(
        action, "run_teacher_retained_paper_dispatch",
        lambda *_a, **_kw: pytest.fail("V called a Core dispatcher"),
    )
    out = StringIO()
    nav = run_post_retention_teacher_menu(
        retained, input_stream=StringIO("V\nB\n"), output=out,
        show_header=lambda _: None,
    )
    assert nav == "back"
    assert "Source 1, page 1: QR unresolved" in out.getvalue()
    assert "Official-wheel directory:" not in out.getvalue()
    assert not (
        retained.report.plan.workspace_root / "scans/review/resolutions"
    ).exists()


def test_d_path_stops_before_second_consent_and_core_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained, decode, _ = _unroutable(tmp_path)
    events = _actiontests._wire(monkeypatch, decode)
    out = StringIO()
    headers: list[str] = []
    result = run_teacher_retained_paper_dispatch(
        retained, tmp_path / "official-wheels",
        input_stream=StringIO("DISPATCH\nDEFER\n"), output=out,
        show_header=headers.append,
    )
    text = out.getvalue()
    assert result.status == "no_dispatchable_pages"
    assert result.core_review is None
    assert events == ["audit", "prepare"]
    assert len(headers) == 1
    assert "Second Teacher Consent" not in text
    assert "Third Teacher Consent" not in text
    assert "Source 1, page 2: QR unresolved" in text
    assert "No verified Core failure ID" in text
    assert "No producer handler was authorized" in text
    assert not (
        retained.report.plan.workspace_root / "scans/review/resolutions"
    ).exists()


def test_mixed_routable_batch_is_not_misclassified_manual_only(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _slice4._case(tmp_path)
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    assert batch.status == "ready"
    assert "Manual-only follow-up" not in render_retained_request_review(batch)
    with pytest.raises(TeacherPreparationReviewError):
        render_manual_only_followup(batch)


def test_forged_status_and_failure_id_never_qualify_as_manual_only(
    tmp_path: Path,
) -> None:
    retained, decode, _ = _unroutable(tmp_path)
    batch = prepare_retained_pds2_requests(retained, decode=decode)
    first = batch.report.sources[0]
    original = first.pages[0]
    forged = replace(
        original,
        failure_category="dispatch_failed", failure_id="failure_forged",
    )
    bad_source = replace(first, pages=(forged,) + first.pages[1:])
    bad_report = replace(batch.report, sources=(bad_source,))
    with pytest.raises(TeacherPreparationReviewError):
        render_manual_only_followup(replace(batch, report=bad_report))
    nonroute = replace(original, status="retained_only")
    bad_source = replace(first, pages=(nonroute,) + first.pages[1:])
    bad_report = replace(batch.report, sources=(bad_source,))
    with pytest.raises(TeacherPreparationReviewError):
        render_manual_only_followup(replace(batch, report=bad_report))


def test_non_core_data_cannot_be_used_for_manual_followup() -> None:
    with pytest.raises(TeacherPreparationReviewError):
        render_manual_only_followup(object())  # type: ignore[arg-type]
