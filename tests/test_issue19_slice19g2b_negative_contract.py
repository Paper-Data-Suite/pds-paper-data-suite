"""#19G2B contract: no accidental second approval or unbounded file access."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def g2b(monkeypatch: pytest.MonkeyPatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return importlib.import_module("issue19_g2b_installed_negative_home")


@pytest.mark.parametrize("scenario", [
    "missing_wheelhouse", "empty_wheelhouse", "invalid_second_consent",
    "unresolved_only",
])
def test_each_negative_case_selects_both_pages_and_never_dispatches(
    g2b: object, tmp_path: Path, scenario: str,
) -> None:
    transcript = g2b._case_steps(  # type: ignore[attr-defined]
        tmp_path / "suite18_synthetic_workspace", tmp_path / "wheels", scenario,
    )
    choices = transcript.splitlines()
    assert choices[:4] == [
        "9", "2", str(tmp_path / "suite18_synthetic_workspace"), "1",
    ]
    assert choices[4:7] == ["1,2", "P", "R"]
    assert choices.count("1,2") == 1
    assert choices.count("RETAIN") == 1
    assert "DISPATCH" not in choices
    assert choices[-1] == "Q"
    if scenario == "invalid_second_consent":
        assert choices.count("APPROVE") == 1
        assert choices[-4:] == ["APPROVE", "B", "B", "Q"]
    else:
        assert "APPROVE" not in choices
        assert choices[-2:] == ["B", "Q"]


def test_negative_harness_refuses_unapproved_parent(
    g2b: object, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    folder = tmp_path / "wrong-parent"
    folder.mkdir()
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    assert g2b.main([  # type: ignore[attr-defined]
        "--synthetic-parent", str(folder), "--wheelhouse", str(wheels),
    ]) == 2
    printed = capsys.readouterr()
    assert "path_guard" in printed.err
    assert "ACCEPTANCE_PASSED" not in printed.out
    assert "PDS2|" not in printed.err


def test_invalid_scenario_never_emits_positive_consent(
    g2b: object, tmp_path: Path,
) -> None:
    with pytest.raises(Exception, match="invalid_scenario"):
        g2b._case_steps(  # type: ignore[attr-defined]
            tmp_path / "suite18_synthetic_workspace", tmp_path,
            "dispatch",
        )


def test_source_never_delegates_directly_to_core_or_producer() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" /
              "issue19_g2b_installed_negative_home.py").read_text(
                  encoding="utf-8"
              )
    assert "execute_with_core_review(" not in source
    assert "dispatch_routes(" not in source
    assert "handle_scoreform_route(" not in source
    assert "qualified_modules=" not in source
