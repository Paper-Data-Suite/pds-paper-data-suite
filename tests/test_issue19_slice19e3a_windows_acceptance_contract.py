"""#19E3A: no-live-dispatch acceptance runner contract and source hygiene."""

from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/issue19_e3a_windows_installed_acceptance.ps1"
)


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_acceptance_runner_is_explicit_and_offline_by_default() -> None:
    source = _source()
    assert "[Parameter(Mandatory = $true)]" in source
    assert "[string]$Wheelhouse" in source
    assert "[switch]$AllowPyPI" in source
    assert "if (-not $AllowPyPI.IsPresent)" in source
    assert "'--no-index', '--find-links'" in source


def test_acceptance_never_uses_teacher_workspace() -> None:
    source = _source()
    assert "'suite18_synthetic_workspace'" in source
    assert "[IO.Path]::GetTempPath()" in source
    assert "[guid]::NewGuid()" in source
    assert "New-Item -ItemType Directory -Path $workspace" in source
    assert "git archive --format=zip HEAD" in source
    assert "-m scripts.issue18_qualify_official_wheels" in source
    assert "& py -3.11 -m venv $venv" in source
    assert "Python 3.11" in source
    assert "Run from the pds-paper-data-suite checkout" in source


@pytest.mark.parametrize("required", [
    "issue18_qualify_official_wheels.py",
    "issue18_real_producer_rehearsal.py",
    "issue18_positive_scoreform_rehearsal.py",
    "issue18_native_mixed_pdf_rehearsal.py",
    "returned_paper_synthetic_acceptance",
    "--fixture $fixture --wheelhouse $wheelhousePath",
    "-m pip check",
    "-m build --wheel --no-isolation",
])
def test_existing_qualified_acceptance_is_reused(required: str) -> None:
    assert required in _source()


def test_only_exact_approved_wheel_versions() -> None:
    source = _source()
    assert "pds_core-0.6.6-py3-none-any.whl" in source
    assert "scoreform-0.13.0-py3-none-any.whl" in source
    assert "quillan-0.10.6-py3-none-any.whl" in source
    assert "paper_data_suite-0.1.0-py3-none-any.whl" in source
    assert "pypdfium2>=5.13,<6" in source
    assert "zxing-cpp>=2.3,<3" in source


def test_no_arbitrary_dispatch_approval_from_a_diagnostic() -> None:
    source = _source()
    assert "SUITE19_E3A_DISPATCH_REMAINS_DEFAULT_DENY" in source
    assert "teacher UI not exercised" in source
    assert "qualified_modules=frozenset" not in source
    assert "execute_with_core_review(" not in source
    assert "execute_prepared_paper_batch(" not in source


def test_installed_probe_is_from_venv_not_checkout() -> None:
    source = _source()
    assert "installedPython" in source
    assert "importlib.metadata" in source
    assert "location.is_relative_to(root)" in source
    assert "$env:PYTHONPATH = $null" in source
    assert "python -c" in source  # comment forbids the fragile invocation
    assert "[IO.File]::WriteAllText" in source


def test_native_verification_is_not_silently_skipped() -> None:
    source = _source()
    assert "Assert-Exit 'E2 native PDF and E1 complete diagnostic'" in source
    assert "Assert-Exit ('Real synthetic installed acceptance: ' + $script)" in source
    assert "SUITE19_E3A_SYNTHETIC_INSTALLED_ACCEPTANCE_PASSED" in source
    assert "try {" in source and "finally {" in source
