"""#18 Slice 3: retained byte fidelity, exact PDS2 and no-dispatch handoff."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest
from pds_core.module_dispatch import RouteDispatchRequest
from pds_core.scan_retention import RetainedSourceScan

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
    RetentionDecisionV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
    PaperProcessingReportV1,
    build_processing_plan,
    count_processing_outcomes,
)
from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecodeLimits,
    DecoderBackendUnavailable,
)
from paper_data_suite.returned_paper_retained_requests import (
    PreparedPageRequestV1,
    RetainedRequestError,
    prepare_retained_pds2_requests,
)


def _code(module: str, route: str = "route_001") -> str:
    return f"PDS2|m={module}|c=english12_p4|w=essay|r={route}"


def _preview(pages: tuple[DecodedPage, ...]) -> tuple[PagePreview, ...]:
    results: list[PagePreview] = []
    for number, page in enumerate(pages, 1):
        values = tuple(dict.fromkeys(page.payloads))
        if page.failed:
            results.append(PagePreview(number, "page_decode_failed"))
        elif page.truncated or len(values) > 1:
            results.append(PagePreview(number, "ambiguous_qr"))
        elif not values:
            results.append(PagePreview(number, "missing_qr"))
        elif values[0].startswith("PDS2|m=") and len(values[0]) < 256:
            module = values[0].split("|", 2)[1][2:]
            results.append(PagePreview(number, "candidate_unverified", module))
        else:
            results.append(PagePreview(number, "invalid_or_foreign_qr"))
    return tuple(results)


def _case(
    tmp_path: Path,
    page_sets: tuple[tuple[DecodedPage, ...], ...] | None = None,
    selected: tuple[tuple[int, int], ...] | None = None,
) -> tuple[
    AuthorizedRetentionResultV1,
    Callable[[bytes, str, DecodeLimits], tuple[DecodedPage, ...]],
    tuple[Path, ...],
]:
    if page_sets is None:
        page_sets = ((
            DecodedPage((_code("scoreform"),)), DecodedPage(),
        ),)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    originals = tmp_path / "originals"
    originals.mkdir()
    paths: list[Path] = []
    snapshots: list[SourcePreview] = []
    content_to_pages: dict[bytes, tuple[DecodedPage, ...]] = {}
    for number, pages in enumerate(page_sets, 1):
        path = originals / f"source_{number}.pdf"
        data = f"%PDF-1.4\n% synthetic source {number}\n".encode("ascii")
        path.write_bytes(data)
        paths.append(path)
        content_to_pages[data] = pages
        snapshots.append(SourcePreview(
            number, "observed", _preview(pages), hashlib.sha256(data).hexdigest(),
        ))
    if selected is None:
        selected = tuple(
            (i, n) for i, pages in enumerate(page_sets, 1)
            for n in range(1, len(pages) + 1)
        )
    plan: PaperProcessingPlanV1 = build_processing_plan(
        workspace, tuple(paths), IntakePreview(tuple(snapshots), ()), selected,
    )

    def observe(chosen: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        return tuple(
            SourcePreview(
                n, "observed", snapshots[paths.index(path)].pages,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for n, path in enumerate(chosen, 1)
        )

    def approve(review):
        return RetentionDecisionV1("approve", review.plan_digest, review.challenge)

    retained = authorize_and_retain_sources(plan, approve=approve, observe=observe)
    assert retained.status == "retained"

    def decode(data: bytes, _format: str, _limits: DecodeLimits):
        return content_to_pages[data]

    return retained, decode, tuple(paths)


def test_requests_are_real_core_objects_and_sorted_by_physical_order(
    tmp_path: Path,
) -> None:
    retention, decoder, _ = _case(
        tmp_path,
        page_sets=((DecodedPage((_code("scoreform", "route_1"),)),
                    DecodedPage((_code("quillan", "route_2"),))),
                   (DecodedPage((_code("vitrine", "route_3"),)),)),
        selected=((2, 1), (1, 2), (1, 1)),
    )
    result = prepare_retained_pds2_requests(retention, decode=decoder)
    assert result.status == "ready"
    assert result.reason == "none"
    assert [(x.source_number, x.page_number) for x in result.candidates] == [
        (1, 1), (1, 2), (2, 1),
    ]
    assert all(isinstance(x.request, RouteDispatchRequest) for x in result.candidates)
    assert [x.request.locator.module_id for x in result.candidates] == [
        "scoreform", "quillan", "vitrine",
    ]
    for item in result.candidates:
        receipt = result.report.sources[item.source_number - 1].retained_source
        assert isinstance(receipt, RetainedSourceScan)
        assert item.request.retained_source is receipt
        assert item.request.source_page_number == item.page_number


def test_unselected_pages_never_become_requests(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path, selected=((1, 1),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert len(batch.candidates) == 1
    assert count_processing_outcomes(batch.report) == (
        ("not_selected", 1), ("retained_only", 1),
    )
    assert batch.report.sources[0].pages[1].route_locator is None


@pytest.mark.parametrize("page", [
    DecodedPage(), DecodedPage(failed=True),
    DecodedPage(("PDS1|m=scoreform",)),
    DecodedPage(("OMR1",)),
    DecodedPage((_code("scoreform"), _code("quillan"))),
    DecodedPage((_code("scoreform"),), truncated=True),
])
def test_unresolved_selected_pages_do_not_dispatch(
    tmp_path: Path, page: DecodedPage,
) -> None:
    retention, decoder, _ = _case(tmp_path, ((page,),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "no_dispatchable_pages"
    assert batch.reason == "no_valid_selected_routes"
    assert not batch.candidates
    assert batch.report.sources[0].pages[0].status == "unresolved_qr"


def test_identical_repeated_qr_codes_are_one_candidate(tmp_path: Path) -> None:
    payload = _code("concord")
    retention, decoder, _ = _case(tmp_path, ((DecodedPage((payload, payload)),),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "ready"
    assert len(batch.candidates) == 1
    assert batch.candidates[0].request.locator.module_id == "concord"


def test_unpublished_provider_is_not_assumed_dispatchable(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path, ((
        DecodedPage((_code("portia"),)),
    ),))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    # Slice 3 parses syntax. Slice 4 must check actual strict installed registry.
    assert batch.candidates[0].request.locator.module_id == "portia"
    assert batch.report.sources[0].pages[0].status == "retained_only"


def test_retained_copy_tampering_fail_closed_without_requests(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path)
    receipt = retention.report.sources[0].retained_source
    assert receipt is not None
    receipt.retained_source_path.write_bytes(b"%PDF-1.4\n% malicious change\n")
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "uncertain"
    assert batch.reason == "retained_unverifiable"
    assert batch.candidates == ()
    assert batch.report.sources[0].retention_status == "uncertain"
    assert batch.report.sources[0].pages[0].status == "uncertain"


def test_deleted_retained_copy_refuses_without_retain_replay(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path)
    receipt = retention.report.sources[0].retained_source
    assert receipt is not None
    receipt.retained_source_path.unlink()
    assert prepare_retained_pds2_requests(
        retention, decode=decoder,
    ).status == "uncertain"
    assert not receipt.retained_source_path.exists()


def test_missing_backend_blocks_every_candidate(tmp_path: Path) -> None:
    retention, _, _ = _case(tmp_path)

    def no_backend(_data, _fmt, _limits):
        raise DecoderBackendUnavailable("synthetic backend unavailable")

    result = prepare_retained_pds2_requests(retention, decode=no_backend)
    assert result.status == "blocked"
    assert result.reason == "decoder_unavailable"
    assert not result.candidates
    assert count_processing_outcomes(result.report) == (
        ("retained_only", 2),
    )


def test_native_decoder_failure_does_not_escape_or_dispatch(tmp_path: Path) -> None:
    retention, _, _ = _case(tmp_path)

    def raise_decoder(_data, _fmt, _limits):
        raise RuntimeError("a private path and student token")

    batch = prepare_retained_pds2_requests(retention, decode=raise_decoder)
    assert batch.status == "blocked"
    assert batch.reason == "decode_failed"
    assert "student token" not in repr(batch)


@pytest.mark.parametrize("changed", ["count", "module", "status", "invalid"])
def test_fresh_observation_drift_is_uncertain(
    tmp_path: Path, changed: str,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    def altered(data, fmt, limits):
        rows = decoder(data, fmt, limits)
        if changed == "count":
            return rows[:1]
        if changed == "module":
            return (DecodedPage((_code("quillan"),)), *rows[1:])
        if changed == "status":
            return (DecodedPage(), *rows[1:])
        return "wrong type"

    batch = prepare_retained_pds2_requests(retention, decode=altered)
    assert batch.status == "uncertain"
    assert batch.reason == "source_observation_changed"
    assert not batch.candidates


def test_original_removed_after_core_retention_is_not_reread(
    tmp_path: Path,
) -> None:
    retention, decoder, originals = _case(tmp_path)
    originals[0].unlink()
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "ready"
    assert len(batch.candidates) == 1


def test_no_new_files_on_prepare_and_no_module_handler_calls(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path)
    before = sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob("*"))
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert batch.status == "ready"
    after = sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob("*"))
    assert before == after


def test_unapproved_or_partial_retention_is_never_promoted(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path)
    for invalid in (
        replace(retention, status="partial"),
        replace(retention, status="cancelled", approved=False),
    ):
        with pytest.raises(RetainedRequestError, match="approved Core retention"):
            prepare_retained_pds2_requests(invalid, decode=decoder)


def test_wrong_core_receipt_refuses_without_fake_renaming(tmp_path: Path) -> None:
    retention, decoder, _ = _case(tmp_path)
    report = retention.report
    receipt = report.sources[0].retained_source
    assert receipt is not None
    wrong = replace(receipt, source_sha256="0" * 64)
    row = replace(report.sources[0], retained_source=wrong)
    invalid_report = PaperProcessingReportV1(report.plan, (row,))
    invalid = replace(retention, report=invalid_report)
    batch = prepare_retained_pds2_requests(invalid, decode=decoder)
    assert batch.status == "uncertain"
    assert batch.candidates == ()


def test_prepared_batch_cannot_contain_unselected_or_unsorted_requests(
    tmp_path: Path,
) -> None:
    retention, decoder, _ = _case(tmp_path, selected=((1, 1),))
    result = prepare_retained_pds2_requests(retention, decode=decoder)
    request = result.candidates[0].request
    with pytest.raises(RetainedRequestError, match="repeated"):
        replace(result, candidates=result.candidates * 2)
    with pytest.raises(RetainedRequestError, match="not typed"):
        replace(result, candidates=(request,))  # type: ignore[arg-type]
    with pytest.raises(RetainedRequestError, match="position"):
        PreparedPageRequestV1(1, 2, request)


def test_safe_repr_contains_no_private_paths_or_raw_qr(tmp_path: Path) -> None:
    retention, decoder, originals = _case(tmp_path)
    batch = prepare_retained_pds2_requests(retention, decode=decoder)
    assert str(originals[0]) not in repr(batch)
    assert _code("scoreform") not in repr(batch)
    assert "PreparedDispatchBatchV1" in repr(batch)


def test_later_source_drift_refuses_all_prepared_requests(tmp_path: Path) -> None:
    sets = ((DecodedPage((_code("scoreform"),)),),
            (DecodedPage((_code("quillan"),)),))
    retention, decode, _ = _case(tmp_path, page_sets=sets)

    def second_changes(data, fmt, limits):
        rows = decode(data, fmt, limits)
        if b"source 2" in data:
            return (DecodedPage(),)
        return rows

    result = prepare_retained_pds2_requests(retention, decode=second_changes)
    assert result.status == "uncertain"
    assert result.candidates == ()
    assert result.report.sources[0].pages[0].status == "retained_only"
    assert result.report.sources[1].pages[0].status == "uncertain"


def test_selected_unresolved_and_valid_page_preserve_both(tmp_path: Path) -> None:
    retention, decode, _ = _case(tmp_path)
    result = prepare_retained_pds2_requests(retention, decode=decode)
    assert result.status == "ready"
    assert len(result.candidates) == 1
    assert count_processing_outcomes(result.report) == (
        ("retained_only", 1), ("unresolved_qr", 1),
    )


def test_unselected_page_observation_drift_still_blocks(tmp_path: Path) -> None:
    retention, decode, _ = _case(tmp_path, selected=((1, 1),))

    def altered(data, fmt, limits):
        rows = decode(data, fmt, limits)
        return (rows[0], DecodedPage((_code("vitrine"),)))

    result = prepare_retained_pds2_requests(retention, decode=altered)
    assert result.status == "uncertain"
    assert not result.candidates
