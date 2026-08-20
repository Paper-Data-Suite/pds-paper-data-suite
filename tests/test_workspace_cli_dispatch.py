from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite.cli import main


def test_workspace_without_subcommand_prints_workspace_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("workspace",)) == 0
    output = capsys.readouterr().out
    assert "usage: pds workspace" in output
    assert "setup" in output
    assert "show" in output
    assert "validate" in output
    assert "set" in output
    assert "reset" in output


def test_workspace_help_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("workspace", "--help"))
    assert raised.value.code == 0
    assert "usage: pds workspace" in capsys.readouterr().out


def test_workspace_setup_help_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("workspace", "setup", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds workspace setup" in output
    assert "guided" in output.lower()


def test_workspace_validate_help_describes_optional_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("workspace", "validate", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds workspace validate" in output
    assert "path" in output


def test_workspace_setup_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_data_suite.cli as cli

    monkeypatch.setattr(cli, "run_workspace_setup", lambda: 5)

    assert main(("workspace", "setup")) == 5


def test_workspace_show_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_data_suite.cli as cli

    monkeypatch.setattr(cli, "run_workspace_show", lambda: 7)

    assert main(("workspace", "show")) == 7


def test_workspace_validate_dispatches_optional_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.cli as cli

    observed: list[Path | None] = []

    def run(path: Path | None) -> int:
        observed.append(path)
        return 0

    monkeypatch.setattr(cli, "run_workspace_validate", run)

    assert main(("workspace", "validate")) == 0
    assert main(("workspace", "validate", "D:/PDS Workspace")) == 0
    assert observed == [None, Path("D:/PDS Workspace")]


def test_workspace_set_dispatches_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_data_suite.cli as cli

    observed: list[Path] = []

    def run(path: Path) -> int:
        observed.append(path)
        return 0

    monkeypatch.setattr(cli, "run_workspace_set", run)

    assert main(("workspace", "set", "D:/PDS Workspace")) == 0
    assert observed == [Path("D:/PDS Workspace")]


def test_workspace_reset_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_data_suite.cli as cli

    monkeypatch.setattr(cli, "run_workspace_reset", lambda: 6)

    assert main(("workspace", "reset")) == 6
