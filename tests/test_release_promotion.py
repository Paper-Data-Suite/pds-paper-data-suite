from __future__ import annotations

import json
from pathlib import Path

from paper_data_suite import __version__

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = (
    _ROOT
    / "paper_data_suite"
    / "data"
    / "release_compatibility_v1.json"
)


def test_promoted_identity_is_exact_and_release_status_is_final() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert __version__ == "0.1.0"
    assert manifest["suite"]["distribution"] == "paper-data-suite"
    assert manifest["suite"]["version"] == "0.1.0"
    assert manifest["suite"]["release_status"] == "release"


def test_live_release_qualification_surfaces_do_not_target_dev_identity() -> None:
    paths = (
        _ROOT / ".github" / "workflows" / "ci.yml",
        _ROOT / "scripts" / "check_package.py",
        _ROOT / "scripts" / "run_windows_pilot_smoke.py",
    )
    for path in paths:
        assert "0.1.0.dev0" not in path.read_text(encoding="utf-8")


def test_final_package_validator_requires_release_status() -> None:
    text = (_ROOT / "scripts" / "check_package.py").read_text(
        encoding="utf-8"
    )

    assert 'EXPECTED_VERSION = "0.1.0"' in text
    assert 'EXPECTED_RELEASE_STATUS = "release"' in text
    assert "compatibility manifest release status disagrees" in text


def test_audit_closes_pre_promotion_gates_but_not_final_disposition() -> None:
    text = (
        _ROOT / "docs" / "releases" / "v0.1.0-release-audit.md"
    ).read_text(encoding="utf-8")

    assert "RA-019" in text
    assert "RA-020" in text
    assert "Release identity gate — satisfied" in text
    assert "all 19 jobs PASS" in text
    assert "Not yet assigned." in text


def test_historical_dev_pilot_evidence_is_preserved() -> None:
    text = (
        _ROOT / "docs" / "operations" / "windows-pilot-smoke.md"
    ).read_text(encoding="utf-8")

    assert "candidate suite identity: `0.1.0.dev0`" in text
    assert (
        "f83e15780d2a5e704f188536587fa4793612df4e18193b0642a6215185cef198"
        in text
    )
