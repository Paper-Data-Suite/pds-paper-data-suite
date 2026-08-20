from __future__ import annotations

import pytest

from paper_data_suite.cli import main


def test_setup_help_describes_current_core_workspace_and_review_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("setup", "--help"))

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds setup" in output
    assert "currently resolved Core workspace" in output
    assert "exact APPLY" in output


def test_setup_dispatches_complete_guided_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    calls: list[str] = []

    def run_setup() -> int:
        calls.append("setup")
        return 7

    monkeypatch.setattr(cli, "run_classroom_setup", run_setup)

    assert main(("setup",)) == 7
    assert calls == ["setup"]
