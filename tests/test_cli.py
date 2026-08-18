from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from paper_data_suite import __version__
from paper_data_suite.cli import main


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
