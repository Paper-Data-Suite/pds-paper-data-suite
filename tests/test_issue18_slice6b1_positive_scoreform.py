"""Pure negative/positive validator tests; official handler runs separately."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def rehearsal() -> ModuleType:
    path = (
        Path(__file__).resolve().parent.parent
        / "scripts/issue18_positive_scoreform_rehearsal.py"
    )
    spec = importlib.util.spec_from_file_location("issue18_positive_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expected_one_to_four_authoritative_answers(rehearsal: ModuleType) -> None:
    answers = ((1, "A", True), (2, "B", True), (3, "C", True), (4, "D", True))
    assert rehearsal._exact_answers(answers)


@pytest.mark.parametrize(
    "answers",
    [
        ((1, "A", True), (2, "B", True), (3, "C", True)),
        ((1, "A", True), (2, "B", True), (4, "C", True), (3, "D", True)),
        ((1, "A", True), (2, "B", False), (3, "C", True), (4, "D", True)),
        ((1, "A", True), (2, "C", True), (3, "C", True), (4, "D", True)),
        ((1, "A", 1), (2, "B", True), (3, "C", True), (4, "D", True)),
        ((1, "A", True), (2, "B", True), (3, "C", True), (4, "D", 1)),
        ((1, "A", True), (2, "B", True), (3, "C", True), (4, "D", True),
         (5, "A", True)),
    ],
)
def test_inexact_or_ambiguous_results_refused(
    rehearsal: ModuleType, answers: tuple[tuple[object, ...], ...]
) -> None:
    assert not rehearsal._exact_answers(answers)


def test_rejects_nonempty_or_wrong_named_workspace(
    rehearsal: ModuleType, tmp_path: Path
) -> None:
    wrong = tmp_path / "other_workspace"
    wrong.mkdir()
    assert not rehearsal._safe_empty_workspace(wrong)
    selected = tmp_path / "suite18_synthetic_workspace"
    selected.mkdir()
    (selected / "existing.txt").write_text("not disposable", encoding="utf-8")
    assert not rehearsal._safe_empty_workspace(selected)


def test_refuses_symlinked_workspace_if_supported(
    rehearsal: ModuleType, tmp_path: Path
) -> None:
    actual = tmp_path / "real"
    actual.mkdir()
    linked = tmp_path / "suite18_synthetic_workspace"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink privilege unavailable: {error}")
    assert not rehearsal._safe_empty_workspace(linked)
