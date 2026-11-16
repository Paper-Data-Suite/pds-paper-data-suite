"""#19D1: no dispatch from a fresh, explicit Core-retained request review."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
    RetentionDecisionV1,
    RetentionReviewV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    build_processing_plan,
)
from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecoderBackendUnavailable,
)
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_preparation import (
    TeacherPreparationReviewError,
    render_retained_request_review,
    review_core_retained_requests,
)
from paper_data_suite.returned_paper_teacher_retention import (
    run_teacher_first_retention,
)

_CODE = "PDS2|m=scoreform|c=english12_p4|w=essay|r=route_001"


def _retained(
    tmp_path: Path, *, selected: tuple[tuple[int, int], ...] = ((1, 1),)
) -> AuthorizedRetentionResultV1:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "PRIVATE_student.pdf"
    source.write_bytes(b"%PDF-1.4\n% 19D1 synthetic only\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    pages = (
        PagePreview(1, "candidate_unverified", "scoreform"),
        PagePreview(2, "missing_qr"),
    )
    expected = SourcePreview(1, "observed", pages, digest)
    plan = build_processing_plan(
        workspace, (source,), IntakePreview((expected,), ()), selected,
    )

    def observe(_: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        return (SourcePreview(
            1, "observed", pages,
            hashlib.sha256(source.read_bytes()).hexdigest(),
        ),)

    return authorize_and_retain_sources(
        plan,
        approve=lambda review: RetentionDecisionV1(
            "approve", review.plan_digest, review.challenge,
        ),
        observe=observe,
    )


def _decode(*_: object) -> tuple[DecodedPage, ...]:
    return (DecodedPage((_CODE,)), DecodedPage())


def _prepared(retention: AuthorizedRetentionResultV1):
    return prepare_retained_pds2_requests(retention, decode=_decode)


def test_real_core_retention_prepares_only_selected_physical_pages(
    tmp_path: Path,
) -> None:
    retention = _retained(tmp_path)
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    text = review_core_retained_requests(retention, prepare=_prepared)
    after = sorted(str(path) for path in tmp_path.rglob("*"))
    assert before == after
    assert "Preparation status: ready" in text
    assert "Selected physical pages: 1" in text
    assert "Prepared typed Core requests: 1" in text
    assert "scoreform: 1" in text
    assert "UNQUALIFIED" in text
    assert "NOT second teacher consent" in text
    assert str(tmp_path) not in text and "PRIVATE" not in text
    assert _CODE not in text and "english12" not in text


def test_missing_qr_selected_does_not_claim_dispatchable_page(
    tmp_path: Path,
) -> None:
    retention = _retained(tmp_path, selected=((1, 2),))
    text = review_core_retained_requests(retention, prepare=_prepared)
    assert "no_dispatchable_pages" in text
    assert "Unresolved selected physical pages: 1" in text
    assert "Prepared typed Core requests: 0" in text


def test_missing_native_decoder_is_blocked_without_claimed_requests(
    tmp_path: Path,
) -> None:
    retention = _retained(tmp_path)

    def blocked(*_: object) -> tuple[DecodedPage, ...]:
        raise DecoderBackendUnavailable("PRIVATE environment")

    text = review_core_retained_requests(
        retention, prepare=lambda result: prepare_retained_pds2_requests(
            result, decode=blocked,
        ),
    )
    assert "Preparation status: blocked" in text
    assert "PRIVATE" not in text
    assert "Prepared typed Core requests: 0" in text


def test_changed_retained_bytes_are_uncertain_not_dispatched(
    tmp_path: Path,
) -> None:
    retention = _retained(tmp_path)
    receipt = retention.report.sources[0].retained_source
    assert receipt is not None
    receipt.retained_source_path.write_bytes(b"corrupted")
    text = review_core_retained_requests(retention, prepare=_prepared)
    assert "Preparation status: uncertain" in text
    assert "Stop; reconcile Core custody" in text
    assert "Prepared typed Core requests: 0" in text


@pytest.mark.parametrize("state,approved", [
    ("cancelled", False), ("partial", True), ("uncertain", True),
    ("rejected", False),
])
def test_incomplete_retention_never_reaches_request_preparation(
    tmp_path: Path, state: str, approved: bool,
) -> None:
    result = replace(_retained(tmp_path), status=state, approved=approved)

    def forbidden(_: AuthorizedRetentionResultV1):
        pytest.fail("incomplete Core custody reached preparation")

    with pytest.raises(TeacherPreparationReviewError):
        review_core_retained_requests(result, prepare=forbidden)


def test_wrong_or_untyped_preparation_refused(tmp_path: Path) -> None:
    retained = _retained(tmp_path)
    with pytest.raises(TeacherPreparationReviewError):
        review_core_retained_requests(retained, prepare=lambda _: object())
    with pytest.raises(TeacherPreparationReviewError):
        review_core_retained_requests(
            retained, prepare=lambda _: (_ for _ in ()).throw(
                RuntimeError("PRIVATE student")
            ),
        )


def test_different_core_custody_report_rejected(tmp_path: Path) -> None:
    first = _retained(tmp_path, selected=((1, 2),))
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = _retained(second_root, selected=((1, 2),))
    wrong = replace(_prepared(first), report=_prepared(second).report)
    with pytest.raises(TeacherPreparationReviewError):
        review_core_retained_requests(first, prepare=lambda _: wrong)


def test_renderer_refuses_arbitrary_result() -> None:
    with pytest.raises(TeacherPreparationReviewError):
        render_retained_request_review(object())  # type: ignore[arg-type]


def _drive(
    tmp_path: Path, transcript: str, monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str, list[str]]:
    retained = _retained(tmp_path)
    calls: list[str] = []
    from paper_data_suite import returned_paper_teacher_preparation as review

    def view(result: AuthorizedRetentionResultV1) -> str:
        assert result is retained
        calls.append("requested")
        return "SAFE PREPARED REQUEST REVIEW\n"

    monkeypatch.setattr(review, "review_core_retained_requests", view)
    output = StringIO()
    # Test the C2 result screen after a real retained Core receipt. The
    # injected action does NOT write a second file and does NOT dispatch.
    def receipt_action(_plan, approve):
        review = RetentionReviewV1(
            workspace_root=retained.report.plan.workspace_root,
            selected_sources=(1,),
            selected_pages=((1, 1),),
            plan_digest="f" * 64,
            challenge="a" * 32,
        )
        decision = approve(review)
        return retained if decision.decision == "approve" else replace(
            retained, status="cancelled", approved=False,
        )

    result = run_teacher_first_retention(
        retained.report.plan,
        input_stream=StringIO(transcript),
        output=output,
        show_header=lambda title: output.write(f"SCREEN {title}\n"),
        execute=receipt_action,
        workspace_guard=lambda _: True,
    )
    return result, output.getvalue(), calls


def test_v_only_after_explicit_retain_and_complete_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigation, text, calls = _drive(tmp_path, "RETAIN\nv\n", monkeypatch)
    assert navigation == "back" and calls == ["requested"]
    assert "SAFE PREPARED REQUEST REVIEW" in text
    assert "V. View prepared Core-retained" in text
    assert "SECRET" not in text and str(tmp_path) not in text


@pytest.mark.parametrize("second,expected", [
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"),
    ("", "back"), ("yes\n", "back"),
])
def test_no_v_means_no_retained_page_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    second: str, expected: str,
) -> None:
    navigation, _, calls = _drive(tmp_path, "RETAIN\n" + second, monkeypatch)
    assert navigation == expected and not calls


def test_cancellation_never_offers_post_retention_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigation, text, calls = _drive(tmp_path, "CANCEL\nv\n", monkeypatch)
    assert navigation == "back" and not calls
    assert "V. View prepared Core-retained" not in text


def test_no_producer_dispatch_import_on_v(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original = builtins.__import__

    def checked(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("paper_data_suite.returned_paper_ordered_dispatch"):
            pytest.fail("V imported producer dispatcher")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    _, _, calls = _drive(tmp_path, "RETAIN\nv\n", monkeypatch)
    assert calls == ["requested"]
