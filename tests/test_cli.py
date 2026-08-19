from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from paper_data_suite import __version__
from paper_data_suite.cli import main
from paper_data_suite.doctor import DiagnosticCheck, DiagnosticStatus, DoctorReport


def _console_script_path() -> Path:
    script_name = "pds.exe" if os.name == "nt" else "pds"
    return Path(sysconfig.get_path("scripts")) / script_name


def test_main_without_arguments_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(()) == 0
    output = capsys.readouterr().out
    assert "usage: pds" in output
    assert "Paper Data Suite" in output
    assert "Operational commands" in output


def test_main_help_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--help",))
    assert raised.value.code == 0
    assert "usage: pds" in capsys.readouterr().out


def test_main_version_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--version",))
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"pds {__version__}"


def test_invalid_argument_returns_usage_failure() -> None:
    with pytest.raises(SystemExit) as raised:
        main(("--unknown",))
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [(), ("--help",), ("--version",)],
)
def test_python_module_cli_is_read_only(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    before = tuple(tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-m", "paper_data_suite", *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert tuple(tmp_path.iterdir()) == before
    assert "usage: pds" in result.stdout or result.stdout.strip() == (
        f"pds {__version__}"
    )


@pytest.mark.parametrize(
    "arguments",
    [(), ("--help",), ("--version",)],
)
def test_installed_console_script_is_read_only(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    executable = _console_script_path()
    assert executable.is_file()
    before = tuple(tmp_path.iterdir())
    result = subprocess.run(
        [str(executable), *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert tuple(tmp_path.iterdir()) == before
    assert "usage: pds" in result.stdout or result.stdout.strip() == (
        f"pds {__version__}"
    )


def test_doctor_help_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("doctor", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds doctor" in output
    assert "--workspace" in output


def test_doctor_dispatches_workspace_and_returns_report_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    observed: list[object] = []
    report = DoctorReport(
        (
            DiagnosticCheck(
                section="Runtime",
                code="runtime.fail",
                status=DiagnosticStatus.FAIL,
                summary="blocked",
            ),
        )
    )

    def collect(*, workspace: object = None) -> DoctorReport:
        observed.append(workspace)
        return report

    monkeypatch.setattr(cli, "collect_doctor_diagnostics", collect)
    monkeypatch.setattr(cli, "render_doctor_report", lambda value: "doctor output\n")

    assert main(("doctor", "--workspace", "D:/PDS Workspace")) == 1
    assert observed == [Path("D:/PDS Workspace")]
    assert capsys.readouterr().out == "doctor output\n"


def test_doctor_warn_only_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    report = DoctorReport(
        (
            DiagnosticCheck(
                section="Suite",
                code="suite.warn",
                status=DiagnosticStatus.WARN,
                summary="attention",
            ),
        )
    )
    monkeypatch.setattr(cli, "collect_doctor_diagnostics", lambda **kwargs: report)
    monkeypatch.setattr(cli, "render_doctor_report", lambda value: "warning\n")

    assert main(("doctor",)) == 0
    assert capsys.readouterr().out == "warning\n"
