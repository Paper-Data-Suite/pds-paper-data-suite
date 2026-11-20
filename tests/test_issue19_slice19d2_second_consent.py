"""#19D2: fresh second teacher decision, not a producer-execution trigger."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite.returned_paper_ordered_dispatch import (
    DispatchDecisionV1,
    DispatchReviewV1,
)
from paper_data_suite.returned_paper_teacher_second_consent import (
    SecondConsentReviewError,
    ask_teacher_second_dispatch_consent,
    make_teacher_dispatch_approver,
)


def _review(root: Path, **changes: object) -> DispatchReviewV1:
    initial = DispatchReviewV1(
        workspace_root=root,
        plan_digest="a" * 64,
        challenge="b" * 32,
        selected_pages=((1, 1), (1, 2), (2, 1), (2, 2)),
        modules=(("quillan", 1), ("scoreform", 1), ("vitrine", 1)),
        eligible_modules=("quillan", "scoreform"),
    )
    return replace(initial, **changes)


def _run(
    review: DispatchReviewV1,
    answer: str,
    *,
    guard: Callable[[Path], bool] | None = None,
) -> tuple[DispatchDecisionV1, str, list[str]]:
    output = StringIO()
    headers: list[str] = []
    decision = ask_teacher_second_dispatch_consent(
        review,
        input_stream=StringIO(answer),
        output=output,
        show_header=headers.append,
        workspace_guard=guard or (lambda _: True),
    )
    return decision, output.getvalue(), headers


def test_exact_second_consent_requires_explicit_dispatch(tmp_path: Path) -> None:
    review = _review(tmp_path)
    actual, text, headers = _run(review, "DISPATCH\n")
    assert actual == DispatchDecisionV1(
        "approve", review.plan_digest, review.challenge,
    )
    assert len(headers) == 1
    assert "Second Teacher Consent" in headers[0]
    assert "Selected physical pages: 4." in text
    assert "Prepared Core route requests: 3." in text
    assert "Requests with an admitted module candidate: 2." in text
    assert "Requests without an admitted module: 1." in text
    assert "Selected pages without a prepared route: 1." in text
    assert "scoreform: 1" in text and "quillan: 1" in text
    assert "MAY write" in text and "NOT a published grade" in text
    assert "vitrine" not in text  # no unqualified routing detail in disclosure
    assert str(tmp_path) not in text


@pytest.mark.parametrize("answer", [
    "", "\n", "CANCEL\n", "yes\n", "retain\n", "process\n",
    "b\n", "m\n", "q\n", "DISPATCH LATER\n", "DISPATCH\x00\n",
    "x" * 75 + "\n", "D I S P A T C H\n", "1\n",
])
def test_ambiguous_or_navigation_answer_always_cancels(
    tmp_path: Path, answer: str,
) -> None:
    review = _review(tmp_path)
    result, text, headers = _run(review, answer)
    assert result.decision == "cancel"
    assert result.plan_digest == review.plan_digest
    assert result.challenge == review.challenge
    assert len(headers) == 1
    assert "Second consent cancelled" in text


def test_case_insensitive_explicit_word_still_requires_unique_review(
    tmp_path: Path,
) -> None:
    first = _review(tmp_path)
    second = replace(first, challenge="c" * 32)
    a, _, _ = _run(first, "dIsPaTcH\n")
    b, _, _ = _run(second, "DISPATCH\n")
    assert a.decision == b.decision == "approve"
    assert a.challenge != b.challenge
    assert a.plan_digest == b.plan_digest


@pytest.mark.parametrize("eligible", [(), ("scoreform",)])
def test_zero_eligible_candidate_refused_without_prompt(
    tmp_path: Path, eligible: tuple[str, ...],
) -> None:
    review = _review(
        tmp_path,
        modules=(("quillan", 1), ("vitrine", 1)),
        eligible_modules=eligible,
    )
    result, text, headers = _run(review, "DISPATCH\n")
    assert result.decision == "cancel"
    assert not headers
    assert "No candidate pages have an admitted producer" in text


def test_only_admitted_candidates_count_not_all_routes(tmp_path: Path) -> None:
    review = _review(tmp_path, eligible_modules=("scoreform",))
    result, text, _ = _run(review, "DISPATCH\n")
    assert result.decision == "approve"
    assert "Requests with an admitted module candidate: 1" in text
    assert "Requests without an admitted module: 2" in text
    assert "quillan: " not in text


@pytest.mark.parametrize("changes", [
    {"plan_digest": "WRONG"},
    {"challenge": "invalid"},
    {"workspace_root": Path("relative")},
    {"retained_sources_are_immutable": False},
    {"producer_handlers_may_write": False},
    {"selected_pages": ()},
    {"selected_pages": ((1, 1), (1, 1))},
    {"selected_pages": ((0, 1),)},
    {"selected_pages": ((9, 1),)},
    {"selected_pages": ((1, 65),)},
    {"modules": ()},
    {"modules": (("scoreform", 0),)},
    {"modules": (("scoreform", 2), ("scoreform", 1))},
    {"modules": (("private\x1bsource", 1),)},
    {"modules": (("scoreform", 5),)},
    {"eligible_modules": ("scoreform", "scoreform")},
    {"eligible_modules": ("vitrine",)},
    {"eligible_modules": ("scoreform", "quillan", "other")},
])
def test_malformed_or_forged_review_refused_before_consent(
    tmp_path: Path, changes: dict[str, object],
) -> None:
    review = _review(tmp_path, **changes)
    with pytest.raises(SecondConsentReviewError):
        _run(review, "DISPATCH\n")


def test_non_review_refused(tmp_path: Path) -> None:
    with pytest.raises(SecondConsentReviewError):
        ask_teacher_second_dispatch_consent(
            object(),  # type: ignore[arg-type]
            input_stream=StringIO("DISPATCH\n"),
            output=StringIO(),
            show_header=lambda _: None,
        )


def test_workspace_mismatch_refused_before_prompt(tmp_path: Path) -> None:
    called = 0

    def guard(root: Path) -> bool:
        nonlocal called
        called += 1
        assert root == tmp_path
        return False

    result, text, headers = _run(_review(tmp_path), "DISPATCH\n", guard=guard)
    assert called == 1
    assert result.decision == "cancel"
    assert not headers
    assert "Active Core workspace" in text


def test_workspace_change_during_confirmation_cancels(tmp_path: Path) -> None:
    called = 0

    def guard(_: Path) -> bool:
        nonlocal called
        called += 1
        return called == 1

    result, text, headers = _run(_review(tmp_path), "DISPATCH\n", guard=guard)
    assert called == 2
    assert len(headers) == 1
    assert result.decision == "cancel"
    assert "workspace changed" in text


def test_exception_in_workspace_guard_never_leaks(tmp_path: Path) -> None:
    def broken(_: Path) -> bool:
        raise OSError("PRIVATE STUDENT NAME SECRET")

    result, text, _ = _run(_review(tmp_path), "DISPATCH\n", guard=broken)
    assert result.decision == "cancel"
    assert "PRIVATE" not in text and "SECRET" not in text


def test_input_io_error_is_cancelled(tmp_path: Path) -> None:
    class BrokenStream(StringIO):
        def readline(self, size: int = -1) -> str:
            raise OSError("private source")

    output = StringIO()
    review = _review(tmp_path)
    result = ask_teacher_second_dispatch_consent(
        review, input_stream=BrokenStream("DISPATCH\n"), output=output,
        show_header=lambda _: None, workspace_guard=lambda _: True,
    )
    assert result.decision == "cancel"
    assert "private source" not in output.getvalue()


def test_factory_is_inert_until_called(tmp_path: Path) -> None:
    output = StringIO()
    called: list[str] = []
    approver = make_teacher_dispatch_approver(
        input_stream=StringIO("DISPATCH\n"), output=output,
        show_header=called.append, workspace_guard=lambda _: True,
    )
    assert not called and not output.getvalue()
    decision = approver(_review(tmp_path))
    assert decision.decision == "approve" and len(called) == 1


def test_factory_rejects_invalid_callbacks() -> None:
    with pytest.raises(SecondConsentReviewError):
        make_teacher_dispatch_approver(
            input_stream=StringIO(""), output=StringIO(),
            show_header=None,  # type: ignore[arg-type]
        )


def test_callback_never_imports_dispatcher_or_producer_at_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(("scoreform", "quillan")):
            pytest.fail("consent callback imported a producer")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    _, output, _ = _run(_review(tmp_path), "DISPATCH\n")
    assert "handler result is NOT" in output


def test_consent_only_returns_decision_and_creates_no_files(tmp_path: Path) -> None:
    before = tuple(tmp_path.rglob("*"))
    decision, _, _ = _run(_review(tmp_path), "DISPATCH\n")
    assert decision.decision == "approve"
    assert tuple(tmp_path.rglob("*")) == before


def test_review_without_qualified_producers_never_reads_input(
    tmp_path: Path,
) -> None:
    class Unreadable(StringIO):
        def readline(self, size: int = -1) -> str:
            pytest.fail("No active admission should cause no prompt")

    result = ask_teacher_second_dispatch_consent(
        _review(tmp_path, eligible_modules=()),
        input_stream=Unreadable("DISPATCH\n"), output=StringIO(),
        show_header=lambda _: pytest.fail("unexpected consent screen"),
        workspace_guard=lambda _: pytest.fail("unexpected workspace probe"),
    )
    assert result.decision == "cancel"
