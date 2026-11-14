"""#18 Slice 2: synthetic explicit approval and real Core retained-source tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_authorized_retention import (
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
    build_processing_plan,
    count_processing_outcomes,
)


def _pdf_bytes(label: str) -> bytes:
    return ("%PDF-1.4\n% wholly synthetic " + label + "\n").encode()


def _case(
    tmp_path: Path, *, two: bool = False,
) -> tuple[PaperProcessingPlanV1, tuple[Path, ...]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    selected = tmp_path / "files"
    selected.mkdir()
    names = ("first.pdf", "second.pdf") if two else ("first.pdf",)
    paths = tuple(selected / name for name in names)
    rows = []
    for index, path in enumerate(paths, 1):
        path.write_bytes(_pdf_bytes(path.stem))
        pages = (PagePreview(1, "candidate_unverified", "scoreform"),
                 PagePreview(2, "missing_qr"))
        rows.append(SourcePreview(
            index, "observed", pages, hashlib.sha256(path.read_bytes()).hexdigest(),
        ))
    preview = IntakePreview(tuple(rows), ())
    coords = ((1, 1), (2, 1)) if two else ((1, 1),)
    return build_processing_plan(workspace, paths, preview, coords), paths


def _observe(plan: PaperProcessingPlanV1):
    def observe(paths: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        results: list[SourcePreview] = []
        for i, path in enumerate(paths, 1):
            index = next(
                pos for pos, row in enumerate(plan.sources)
                if row.source_path == path
            )
            pages = plan.sources[index].observation.pages
            results.append(SourcePreview(
                i, "observed", pages, hashlib.sha256(path.read_bytes()).hexdigest(),
            ))
        return tuple(results)
    return observe


def _approve(review):
    assert review.selected_files_are_retained_whole is True
    assert review.selected_pages
    return RetentionDecisionV1("approve", review.plan_digest, review.challenge)


def _retention_files(root: Path) -> tuple[Path, ...]:
    folder = root / "scans" / "source"
    return tuple(folder.rglob("*.pdf")) if folder.exists() else ()


def test_preview_only_import_and_plan_never_write(tmp_path: Path) -> None:
    plan, _ = _case(tmp_path)
    assert plan.authorized is False
    assert not (plan.workspace_root / "scans").exists()


def test_explicit_cancel_is_before_any_core_write(tmp_path: Path) -> None:
    plan, _ = _case(tmp_path)
    calls: list[str] = []
    result = authorize_and_retain_sources(
        plan, observe=_observe(plan),
        approve=lambda r: RetentionDecisionV1(
            "cancel", r.plan_digest, r.challenge,
        ),
        retain=lambda _root, _path: calls.append("bad"),  # type: ignore[arg-type]
    )
    assert result.status == "cancelled"
    assert not result.approved
    assert count_processing_outcomes(result.report) == (
        ("not_attempted", 1), ("not_selected", 1),
    )
    assert calls == []
    assert not (plan.workspace_root / "scans").exists()


@pytest.mark.parametrize("invalid", [
    "wrong-digest", "wrong-challenge", "wrong-type", "raise",
])
def test_invalid_or_stale_approval_never_writes(
    tmp_path: Path, invalid: str,
) -> None:
    plan, _ = _case(tmp_path)
    calls: list[str] = []

    def approve(review):
        if invalid == "raise":
            raise RuntimeError("never leak sensitive teacher data")
        if invalid == "wrong-type":
            return True
        if invalid == "wrong-digest":
            return RetentionDecisionV1("approve", "0" * 64, review.challenge)
        return RetentionDecisionV1("approve", review.plan_digest, "wrong")

    result = authorize_and_retain_sources(
        plan, approve=approve, observe=_observe(plan),
        retain=lambda root, path: calls.append("bad"),  # type: ignore[arg-type]
    )
    assert result.status == "cancelled"
    assert not calls
    assert not _retention_files(plan.workspace_root)


def test_true_approval_calls_real_core_retention_once(tmp_path: Path) -> None:
    from pds_core.scan_retention import retain_source_scan

    plan, paths = _case(tmp_path)
    calls: list[tuple[Path, Path]] = []

    def wrapped(root: Path, source: Path):
        calls.append((root, source))
        return retain_source_scan(root, source)

    result = authorize_and_retain_sources(
        plan, approve=_approve, observe=_observe(plan), retain=wrapped,
    )
    assert result.status == "retained"
    assert result.approved
    assert calls == [(plan.workspace_root, paths[0])]
    assert len(_retention_files(plan.workspace_root)) == 1
    source = result.report.sources[0]
    assert source.retention_status == "retained"
    assert source.retained_source is not None
    assert source.retained_source.source_sha256 == hashlib.sha256(
        paths[0].read_bytes()
    ).hexdigest()
    assert source.pages[0].status == "retained_only"
    assert source.pages[1].status == "not_selected"
    assert paths[0].read_bytes() == _pdf_bytes("first")


def test_stale_source_rejected_before_approval_and_writes(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path)
    paths[0].write_bytes(b"DIFFERENT")
    approvals: list[object] = []
    result = authorize_and_retain_sources(
        plan, observe=_observe(plan),
        approve=lambda r: approvals.append(r),  # type: ignore[arg-type]
    )
    assert result.status == "rejected"
    assert not result.approved
    assert approvals == []
    assert result.report.sources[0].pages[0].status == "source_rejected"
    assert not _retention_files(plan.workspace_root)


def test_page_observation_change_rejected_before_approval(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path)

    def changed(_):
        row = plan.sources[0].observation
        return (replace(row, pages=(
            PagePreview(1, "missing_qr"), row.pages[1],
        )),)

    result = authorize_and_retain_sources(
        plan, approve=_approve, observe=changed,
    )
    assert result.status == "rejected"
    assert not _retention_files(plan.workspace_root)


def test_source_changed_during_approval_refused_before_mutation(
    tmp_path: Path,
) -> None:
    plan, paths = _case(tmp_path)

    def mutate_and_approve(review):
        paths[0].write_bytes(b"changed while teacher reviewed")
        return _approve(review)

    result = authorize_and_retain_sources(
        plan, observe=_observe(plan), approve=mutate_and_approve,
    )
    assert result.status == "rejected"
    assert result.approved
    assert not _retention_files(plan.workspace_root)


def test_core_writer_failure_is_uncertain_not_safe_to_retry(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)
    calls = 0

    def fail(_root: Path, _source: Path):
        nonlocal calls
        calls += 1
        raise OSError("secret printer source path")

    result = authorize_and_retain_sources(
        plan, observe=_observe(plan), approve=_approve, retain=fail,
    )
    assert result.status == "uncertain"
    assert result.approved
    assert calls == 1
    assert result.report.sources[0].retention_status == "uncertain"
    assert result.report.sources[0].pages[0].status == "uncertain"
    assert "secret printer" not in repr(result)


def test_retained_bytes_modified_after_core_copy_produces_uncertain(
    tmp_path: Path,
) -> None:
    from pds_core.scan_retention import retain_source_scan

    plan, _ = _case(tmp_path)

    def corrupt(root: Path, source: Path):
        receipt = retain_source_scan(root, source)
        receipt.retained_source_path.write_bytes(b"changed retained bytes")
        return receipt

    result = authorize_and_retain_sources(
        plan, observe=_observe(plan), approve=_approve, retain=corrupt,
    )
    assert result.status == "uncertain"
    assert len(_retention_files(plan.workspace_root)) == 1
    assert result.report.sources[0].retained_source is None


def test_multiple_selected_sources_are_retained_once_each(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path, two=True)
    result = authorize_and_retain_sources(
        plan, approve=_approve, observe=_observe(plan),
    )
    assert result.status == "retained"
    assert len(_retention_files(plan.workspace_root)) == 2
    assert [row.retention_status for row in result.report.sources] == [
        "retained", "retained",
    ]
    assert [path.read_bytes() for path in paths] == [
        _pdf_bytes("first"), _pdf_bytes("second"),
    ]


def test_partial_after_first_retained_and_second_stale(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path, two=True)
    observed = _observe(plan)
    counts: dict[str, int] = {}

    def stale_second(files: tuple[Path, ...]):
        for path in files:
            counts[path.name] = counts.get(path.name, 0) + 1
            if path == paths[1] and counts[path.name] == 2:
                path.write_bytes(b"stale after approval")
        return observed(files)

    result = authorize_and_retain_sources(
        plan, approve=_approve, observe=stale_second,
    )
    assert result.status == "partial"
    assert len(_retention_files(plan.workspace_root)) == 1
    assert [r.pages[0].status for r in result.report.sources] == [
        "retained_only", "source_rejected",
    ]


def test_symlink_source_refused_without_writer(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path)
    target = tmp_path / "target.pdf"
    target.write_bytes(paths[0].read_bytes())
    paths[0].unlink()
    try:
        paths[0].symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    result = authorize_and_retain_sources(
        plan, observe=_observe(plan), approve=_approve,
    )
    assert result.status == "rejected"
    assert not _retention_files(plan.workspace_root)


def test_different_reuses_require_fresh_review_challenge(tmp_path: Path) -> None:
    plan, _ = _case(tmp_path)
    captured = []

    def cancel(review):
        captured.append(review.challenge)
        return RetentionDecisionV1("cancel", review.plan_digest, review.challenge)

    for _ in range(2):
        result = authorize_and_retain_sources(
            plan, observe=_observe(plan), approve=cancel,
        )
        assert result.status == "cancelled"
    assert len(set(captured)) == 2


def test_privacy_repr_and_no_module_dispatch_claims(tmp_path: Path) -> None:
    plan, paths = _case(tmp_path)
    captured = []

    def approve(review):
        captured.append(review)
        return RetentionDecisionV1("cancel", review.plan_digest, review.challenge)

    result = authorize_and_retain_sources(
        plan, observe=_observe(plan), approve=approve,
    )
    assert str(paths[0]) not in repr(result)
    assert str(paths[0]) not in repr(captured[0])
    assert "handler_returned" not in str(count_processing_outcomes(result.report))
    assert "dispatch_failed" not in str(count_processing_outcomes(result.report))
