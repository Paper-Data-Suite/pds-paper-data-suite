from __future__ import annotations

from importlib import metadata

from paper_data_suite.doctor import (
    DiagnosticStatus,
    collect_release_tooling_diagnostics,
)
from paper_data_suite.release_tooling import load_release_tooling_contract


def _lookup(versions: dict[str, str]):
    def lookup(distribution: str) -> str:
        try:
            return versions[distribution]
        except KeyError as error:
            raise metadata.PackageNotFoundError(distribution) from error

    return lookup


def test_release_tooling_doctor_accepts_exact_pip() -> None:
    report = collect_release_tooling_diagnostics(
        load_release_tooling_contract(),
        version_lookup=_lookup({"pip": "26.2.1"}),
    )
    assert report.exit_code == 0
    check = report.checks[0]
    assert check.code == "tooling.version_match"
    assert check.status is DiagnosticStatus.PASS
    assert "pip 26.2.1" in check.summary


def test_release_tooling_doctor_blocks_missing_or_mismatched_pip() -> None:
    missing = collect_release_tooling_diagnostics(
        load_release_tooling_contract(),
        version_lookup=_lookup({}),
    )
    mismatch = collect_release_tooling_diagnostics(
        load_release_tooling_contract(),
        version_lookup=_lookup({"pip": "24.0"}),
    )
    assert missing.exit_code == 1
    assert missing.checks[0].code == "tooling.missing"
    assert mismatch.exit_code == 1
    assert mismatch.checks[0].code == "tooling.version_mismatch"
    assert "24.0" in mismatch.checks[0].summary
    assert "26.2.1" in mismatch.checks[0].summary
