"""#19E3B3: deliberate Home V->D navigation, custody and admission boundaries."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Callable

import pytest
from test_issue19_slice19c2_teacher_retention import _case, _observer

from paper_data_suite import returned_paper_teacher_dispatch_action as action
from paper_data_suite.returned_paper_authorized_retention import (
    Approver,
    AuthorizedRetentionResultV1,
    RetentionDecisionV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_processing_contract import PaperProcessingPlanV1
from paper_data_suite.returned_paper_teacher_dispatch_menu import (
    _read_bounded,
    _wheelhouse_path,
    run_post_retention_teacher_menu,
)
from paper_data_suite.returned_paper_teacher_retention import (
    run_teacher_first_retention,
)


def _retained(tmp_path: Path) -> AuthorizedRetentionResultV1:
    plan, _ = _case(tmp_path)
    result = authorize_and_retain_sources(
        plan,
        approve=lambda review: RetentionDecisionV1(
            "approve", review.plan_digest, review.challenge,
        ),
        observe=_observer(plan),
    )
    assert result.status == "retained" and result.approved
    return result


def _drive_retention(tmp_path: Path, command: str) -> tuple[str, str]:
    plan, _ = _case(tmp_path)
    output = StringIO()

    def execute(
        chosen: PaperProcessingPlanV1, approve: Approver,
    ) -> AuthorizedRetentionResultV1:
        return authorize_and_retain_sources(
            chosen, approve=approve, observe=_observer(chosen),
        )

    nav = run_teacher_first_retention(
        plan, input_stream=StringIO(command), output=output,
        show_header=lambda title: output.write("HEADER " + title + "\n"),
        execute=execute, workspace_guard=lambda _: True,
    )
    return nav, output.getvalue()


def _block_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        action, "run_teacher_retained_paper_dispatch",
        lambda *_args, **_kwargs: pytest.fail("unexpected dispatch"),
    )


def test_first_retention_only_offers_dispatch_after_verified_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_dispatch(monkeypatch)
    nav, text = _drive_retention(tmp_path, "CANCEL\nD\n")
    assert nav == "back" and "Status: cancelled." in text
    assert "D. Process retained pages" not in text
    assert not (tmp_path / "workspace" / "scans").exists()


def test_retain_then_explicit_d_calls_bridge_once_with_same_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "official-wheels"
    wheelhouse.mkdir()
    received: list[tuple[AuthorizedRetentionResultV1, Path, str]] = []

    def bridge(
        receipt: AuthorizedRetentionResultV1, wheels: Path, *,
        input_stream: StringIO, output: StringIO,
        show_header: Callable[[str], None],
    ) -> None:
        received.append((receipt, wheels, input_stream.readline()))
        output.write("BRIDGE CALLED\n")

    monkeypatch.setattr(action, "run_teacher_retained_paper_dispatch", bridge)
    nav, text = _drive_retention(
        tmp_path, f"RETAIN\nD\n{wheelhouse}\nDISPATCH\n"
    )
    assert nav == "back"
    assert len(received) == 1
    assert received[0][0].approved and received[0][0].status == "retained"
    assert received[0][1] == wheelhouse
    assert received[0][2] == "DISPATCH\n"
    assert "BRIDGE CALLED" in text
    assert "Retain Selected Source Files?" in text
    assert "D. Process retained pages" in text
    assert len(tuple((tmp_path / "workspace" / "scans" / "source").rglob("*.pdf"))) == 1


def test_read_only_v_then_d_reuses_one_retention_not_new_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    calls = []

    def bridge(
        receipt: AuthorizedRetentionResultV1, wheels: Path, **_kwargs: object,
    ) -> None:
        calls.append((receipt, wheels))

    monkeypatch.setattr(action, "run_teacher_retained_paper_dispatch", bridge)
    from paper_data_suite import returned_paper_teacher_preparation as prep
    monkeypatch.setattr(
        prep, "review_core_retained_requests", lambda _: "READ ONLY REVIEW\n",
    )
    nav, text = _drive_retention(tmp_path, f"RETAIN\nV\nD\n{wheelhouse}\n")
    assert nav == "back" and "READ ONLY REVIEW" in text
    assert len(calls) == 1 and calls[0][1] == wheelhouse
    assert len(tuple((tmp_path / "workspace" / "scans" / "source").rglob("*.pdf"))) == 1


@pytest.mark.parametrize("choice,expected", [
    ("b", "back"), ("m", "home"), ("q", "quit"),
])
def test_post_retention_navigation_keeps_bmq(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    choice: str, expected: str,
) -> None:
    _block_dispatch(monkeypatch)
    nav, text = _drive_retention(tmp_path, f"RETAIN\n{choice}\n")
    assert nav == expected
    assert "Status: retained." in text


@pytest.mark.parametrize("choice,expected", [
    ("b", "back"), ("m", "home"), ("q", "quit"),
])
def test_wheelhouse_prompt_navigation_is_not_second_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    choice: str, expected: str,
) -> None:
    _block_dispatch(monkeypatch)
    nav, text = _drive_retention(tmp_path, f"RETAIN\nD\n{choice}\n")
    assert nav == expected and "Official-wheel directory:" in text
    assert "DISPATCH" not in text.split("Official-wheel directory:")[-1]


@pytest.mark.parametrize("bad", [
    "relative/path", "../wheels", "\\\\server\\wheels", "//server/wheels",
    "/", "bad\x00path", "x" * 1030, "",
])
def test_invalid_wheelhouse_fails_before_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    _block_dispatch(monkeypatch)
    nav, text = _drive_retention(tmp_path, f"RETAIN\nD\n{bad}\n")
    assert nav == "back"
    assert "No processing requested" in text or "no processing requested" in text


def test_v_then_quit_does_not_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_dispatch(monkeypatch)
    from paper_data_suite import returned_paper_teacher_preparation as prep
    monkeypatch.setattr(
        prep, "review_core_retained_requests", lambda _: "SAFE PREVIEW\n",
    )
    nav, text = _drive_retention(tmp_path, "RETAIN\nV\nQ\n")
    assert nav == "quit" and "Preparation Review" in text


def test_bridge_exception_never_claims_no_writes_or_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    called: list[int] = []

    def failing(*_args: object, **_kwargs: object) -> None:
        called.append(1)
        raise RuntimeError("PRIVATE STUDENT DATA MAY BE COMMITTED")

    monkeypatch.setattr(action, "run_teacher_retained_paper_dispatch", failing)
    nav, text = _drive_retention(tmp_path, f"RETAIN\nD\n{wheelhouse}\n")
    assert nav == "back" and called == [1]
    assert "effects MAY have occurred" in text
    assert "Do not retry" in text and "PRIVATE STUDENT" not in text


def test_invalid_input_and_eof_cannot_become_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_dispatch(monkeypatch)
    for index, response in enumerate(("", "xx", "D\n")):
        folder = tmp_path / str(index)
        folder.mkdir()
        receipt = _retained(folder)
        output = StringIO()
        nav = run_post_retention_teacher_menu(
            receipt, input_stream=StringIO(response), output=output,
            show_header=lambda _: None,
        )
        assert nav == "back"


def test_path_shape_and_bounded_input() -> None:
    assert _wheelhouse_path("relative/path") is None
    assert _wheelhouse_path("../bad") is None
    assert _wheelhouse_path("//server/wheels") is None
    assert _read_bounded(StringIO("x" * 70 + "\n"), 64) is None
    assert _read_bounded(StringIO("D\n"), 64) == "D"
