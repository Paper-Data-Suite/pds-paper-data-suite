from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_SECURITY = _ROOT / "SECURITY.md"
_PYPROJECT = _ROOT / "pyproject.toml"
_GOVERNANCE = _ROOT / "docs" / "releases" / "v0.1.0-governance.md"
_RELEASE_NOTES = _ROOT / "docs" / "releases" / "v0.1.0.md"


def test_release_gate_is_stable_aggregate_of_release_qualification_jobs() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    block = text[text.index("  release-gate:") :]

    assert "name: release-gate" in block
    assert "if: always()" in block
    for dependency in (
        "validate",
        "combined-installed-suite",
        "release-artifacts",
        "bootstrap-windows",
    ):
        assert f"      - {dependency}" in block
    assert "toJson(needs)" in block
    assert 'facts["result"] != "success"' in block


def test_first_release_uses_alpha_classifier_with_promoted_identity() -> None:
    text = _PYPROJECT.read_text(encoding="utf-8")

    assert "Development Status :: 3 - Alpha" in text
    assert "Development Status :: 2 - Pre-Alpha" not in text

    version_text = (_ROOT / "paper_data_suite" / "_version.py").read_text(
        encoding="utf-8"
    )
    manifest_text = (
        _ROOT
        / "paper_data_suite"
        / "data"
        / "release_compatibility_v1.json"
    ).read_text(encoding="utf-8")
    assert '0.1.0' in version_text
    assert '"version": "0.1.0"' in manifest_text
    assert '"release_status": "release"' in manifest_text


def test_security_policy_defines_latest_pilot_support_without_false_release_claim(
) -> None:
    text = _SECURITY.read_text(encoding="utf-8")

    assert "only the latest released `0.1.x` version is supported" in text
    assert "`main` remains development-only" in text
    assert "Private Vulnerability Reporting" in text
    assert "maintainer-confirmed" in text
    assert "no supported public" in text.lower()


def test_governance_checklist_requires_rulesets_pvr_and_release_gate() -> None:
    text = _GOVERNANCE.read_text(encoding="utf-8")

    assert "0 approving reviews" in text
    assert "`release-gate`" in text
    assert "v*" in text
    assert "Private Vulnerability Reporting" in text
    assert "force pushes" in text
    assert "branch deletion" in text


def test_audit_approved_release_notes_remain_unpublished() -> None:
    text = _RELEASE_NOTES.read_text(encoding="utf-8")

    assert "Windows-first teacher pilot" in text
    assert "macOS is not release-qualified" in text
    assert "Linux CI is software-compatibility evidence" in text
    assert "APPROVE WITH DOCUMENTED NON-BLOCKING LIMITATIONS" in text
    assert (
        "No tag or public release should be created until the remaining\n"
        "publication mechanics are complete."
        in text
    )
