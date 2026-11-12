"""Suite #18 Slice 1: pure synthetic processing-plan and outcome contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    PROCESSING_CONTRACT_VERSION,
    PaperProcessingPlanV1,
    PaperProcessingReportV1,
    PhysicalPageOutcomeV1,
    PlannedSourceV1,
    ProcessingContractError,
    SelectedPhysicalPageV1,
    SourceProcessingOutcomeV1,
    build_processing_plan,
    count_processing_outcomes,
)


def _preview() -> IntakePreview:
    return IntakePreview((
        SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "missing_qr"),
            PagePreview(3, "candidate_unverified", "quillan"),
        ), "a" * 64),
        SourcePreview(2, "source_decode_failed"),
    ), ())


def _plan(tmp_path: Path) -> PaperProcessingPlanV1:
    return build_processing_plan(
        tmp_path / "teacher workspace",
        (tmp_path / "private_a.pdf", tmp_path / "private_b.jpg"),
        _preview(),
        ((1, 3), (1, 2)),
    )


def test_plan_is_nonmutating_immutable_and_not_authorization(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.contract_version == PROCESSING_CONTRACT_VERSION == "1"
    assert plan.authorized is False
    assert [(p.source_number, p.page_number) for p in plan.selected_pages] == [
        (1, 3), (1, 2),
    ]
    assert plan.selected_pages[0].observation.candidate_module_id == "quillan"
    assert not (tmp_path / "teacher workspace").exists()
    assert "private_a" not in repr(plan)
    assert "teacher workspace" not in repr(plan)
    with pytest.raises(FrozenInstanceError):
        plan.authorized = True  # type: ignore[misc]
    with pytest.raises(ProcessingContractError, match="not authorization"):
        replace(plan, authorized=True)  # type: ignore[arg-type]


def test_only_actual_preview_objects_are_joined(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.sources[0].observation is _plan(tmp_path).sources[0].observation or (
        plan.sources[0].observation == _plan(tmp_path).sources[0].observation
    )
    assert not hasattr(plan.selected_pages[0], "route_locator")
    assert not hasattr(plan, "consent_token")


def test_unresolved_page_can_be_deliberately_selected_but_not_assigned_route(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    assert plan.selected_pages[1].observation.status == "missing_qr"
    assert plan.selected_pages[1].observation.candidate_module_id is None


@pytest.mark.parametrize("selection", [
    ((1, 1), (1, 1)),
    ((1, 4),),
    ((3, 1),),
    ((2, 1),),
    ((0, 1),),
    ((1, -2),),
    ((True, 1),),
    ((1, 1.0),),
    ((1,),),
    ((1, 1, 1),),
    ((1, 2),) * 513,
    (),
])
def test_invalid_selection_fails_closed(
    tmp_path: Path, selection: tuple[tuple[object, ...], ...],
) -> None:
    with pytest.raises(ProcessingContractError):
        build_processing_plan(
            tmp_path / "workspace", (tmp_path / "a.pdf", tmp_path / "b.jpg"),
            _preview(), selection,  # type: ignore[arg-type]
        )


def test_invalid_source_mapping_and_path_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ProcessingContractError, match="mapping"):
        build_processing_plan(tmp_path / "workspace", (tmp_path / "a.pdf",),
                              _preview(), ((1, 1),))
    with pytest.raises(ProcessingContractError, match="absolute"):
        build_processing_plan(
            tmp_path / "workspace", (Path("a.pdf"), tmp_path / "b.jpg"),
            _preview(), ((1, 1),),
        )
    with pytest.raises(ProcessingContractError, match="nontraversing"):
        build_processing_plan(tmp_path / ".." / "workspace",
                              (tmp_path / "a.pdf", tmp_path / "b.jpg"),
                              _preview(), ((1, 1),))
    with pytest.raises(ProcessingContractError, match="filesystem root"):
        build_processing_plan(Path(tmp_path.anchor),
                              (tmp_path / "a.pdf", tmp_path / "b.jpg"),
                              _preview(), ((1, 1),))


def test_unobserved_source_does_not_authorize_selection(tmp_path: Path) -> None:
    source = SourcePreview(1, "observed", (PagePreview(1, "missing_qr"),))
    with pytest.raises(ProcessingContractError, match="advisory digest"):
        build_processing_plan(tmp_path / "workspace", (tmp_path / "a.pdf",),
                              IntakePreview((source,), ()), ((1, 1),))


def test_duplicate_or_inconsistent_preview_numbers_fail(tmp_path: Path) -> None:
    original = _plan(tmp_path)
    altered = PlannedSourceV1(tmp_path / "private.pdf", SourcePreview(
        2, "observed", (PagePreview(1, "missing_qr"),), "a" * 64,
    ))
    with pytest.raises(ProcessingContractError, match="one-based"):
        replace(original, sources=(altered, original.sources[1]))
    with pytest.raises(ProcessingContractError, match="selected physical"):
        SelectedPhysicalPageV1(1, 2, PagePreview(1, "missing_qr"))


def test_reports_count_every_physical_page_including_unselected(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    one = SourceProcessingOutcomeV1(1, "not_retained", (
        PhysicalPageOutcomeV1(1, 1, "not_selected"),
        PhysicalPageOutcomeV1(1, 2, "source_rejected"),
        PhysicalPageOutcomeV1(1, 3, "not_attempted"),
    ))
    two = SourceProcessingOutcomeV1(2, "not_retained", ())
    report = PaperProcessingReportV1(plan, (one, two))
    assert count_processing_outcomes(report) == (
        ("not_attempted", 1), ("not_selected", 1), ("source_rejected", 1),
    )
    assert "private_a" not in repr(report)
    assert "retained" not in str(report)  # do not serialize a false receipt


def test_report_rejects_missing_or_reordered_physical_pages(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    with pytest.raises(ProcessingContractError, match="physical pages"):
        SourceProcessingOutcomeV1(1, "not_retained", (
            PhysicalPageOutcomeV1(1, 1, "not_selected"),
            PhysicalPageOutcomeV1(1, 3, "source_rejected"),
        ))
    row = SourceProcessingOutcomeV1(1, "not_retained", (
        PhysicalPageOutcomeV1(1, 1, "not_selected"),
        PhysicalPageOutcomeV1(1, 2, "source_rejected"),
        PhysicalPageOutcomeV1(1, 3, "not_attempted"),
    ))
    with pytest.raises(ProcessingContractError, match="every selected source"):
        PaperProcessingReportV1(plan, (row,))
    with pytest.raises(ProcessingContractError, match="source order"):
        PaperProcessingReportV1(plan, (
            SourceProcessingOutcomeV1(2, "not_retained", ()),
            SourceProcessingOutcomeV1(1, "not_retained", (
                PhysicalPageOutcomeV1(1, 1, "not_selected"),
                PhysicalPageOutcomeV1(1, 2, "not_attempted"),
                PhysicalPageOutcomeV1(1, 3, "not_attempted"),
            )),
        ))


def test_report_rejects_unselected_page_marked_dispatched(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    row = SourceProcessingOutcomeV1(1, "not_retained", (
        PhysicalPageOutcomeV1(1, 1, "source_rejected"),
        PhysicalPageOutcomeV1(1, 2, "source_rejected"),
        PhysicalPageOutcomeV1(1, 3, "not_attempted"),
    ))
    with pytest.raises(ProcessingContractError, match="unapproved page"):
        PaperProcessingReportV1(
            plan, (row, SourceProcessingOutcomeV1(2, "not_retained", ()))
        )


def test_report_rejects_selected_page_silently_omitted(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    row = SourceProcessingOutcomeV1(1, "not_retained", (
        PhysicalPageOutcomeV1(1, 1, "not_selected"),
        PhysicalPageOutcomeV1(1, 2, "not_selected"),
        PhysicalPageOutcomeV1(1, 3, "not_attempted"),
    ))
    with pytest.raises(ProcessingContractError, match="silently omitted"):
        PaperProcessingReportV1(
            plan, (row, SourceProcessingOutcomeV1(2, "not_retained", ()))
        )


def test_unretained_source_cannot_claim_handler_success() -> None:
    with pytest.raises(ProcessingContractError, match="Core locator"):
        PhysicalPageOutcomeV1(1, 1, "handler_returned")
    with pytest.raises(ProcessingContractError, match="Core receipt"):
        SourceProcessingOutcomeV1(1, "retention_failed", (
            PhysicalPageOutcomeV1(1, 1, "retained_only"),
        ))
    with pytest.raises(ProcessingContractError, match="Core receipt"):
        SourceProcessingOutcomeV1(1, "retained", ())


def test_uncertain_without_retention_receipt_cannot_claim_positive_handling() -> None:
    with pytest.raises(ProcessingContractError, match="positive processing claims"):
        SourceProcessingOutcomeV1(1, "uncertain", (
            PhysicalPageOutcomeV1(1, 1, "retained_only"),
        ))
    # A lost receipt after an interrupted writer is UNKNOWN, not no-write proof.
    uncertain = SourceProcessingOutcomeV1(1, "uncertain", (
        PhysicalPageOutcomeV1(1, 1, "uncertain"),
    ))
    assert uncertain.retention_status == "uncertain"


def test_failure_references_are_bounded_and_opaque() -> None:
    with pytest.raises(ProcessingContractError, match="failure category"):
        PhysicalPageOutcomeV1(1, 1, "uncertain", failure_category="C:\\student\\path")
    with pytest.raises(ProcessingContractError, match="failure ID requires"):
        PhysicalPageOutcomeV1(1, 1, "uncertain", failure_id="failure_01")
    with pytest.raises(ProcessingContractError, match="processing proof"):
        PhysicalPageOutcomeV1(1, 1, "not_selected", failure_category="processing_error")
    value = PhysicalPageOutcomeV1(1, 1, "review_write_failed",
                                  failure_category="processing_error")
    assert "processing_error" not in repr(value)


def test_no_io_or_provider_imports_during_contract_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("contract construction must not read files")

    monkeypatch.setattr(builtins, "open", forbidden)
    plan = _plan(tmp_path)
    assert plan.authorized is False
