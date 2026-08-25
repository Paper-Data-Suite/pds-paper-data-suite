from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AUDIT = _ROOT / "docs" / "releases" / "v0.1.0-release-audit.md"
_NOTES = _ROOT / "docs" / "releases" / "v0.1.0.md"
_PILOT = _ROOT / "docs" / "operations" / "windows-pilot-smoke.md"


def test_release_audit_records_windows_pilot_pass() -> None:
    text = _AUDIT.read_text(encoding="utf-8")

    assert "RA-018" in text
    assert "PASS after issue #14 slices 9-9b" in text
    assert "WINDOWS PILOT SMOKE: PASS" in text
    assert "pdftoppm version 25.07.0" in text


def test_pilot_hash_is_explicitly_not_final_release_digest() -> None:
    for path in (_AUDIT, _NOTES, _PILOT):
        text = path.read_text(encoding="utf-8")
        assert (
            "f83e15780d2a5e704f188536587fa4793612df4e18193b0642a6215185cef198"
            in text
        )
        assert "not" in text.lower()
        assert "final release artifact" in text.lower()


def test_release_identity_is_promoted_for_final_qualification() -> None:
    version = (_ROOT / "paper_data_suite" / "_version.py").read_text(
        encoding="utf-8"
    )
    manifest = (
        _ROOT
        / "paper_data_suite"
        / "data"
        / "release_compatibility_v1.json"
    ).read_text(encoding="utf-8")

    assert "0.1.0" in version
    assert '"version": "0.1.0"' in manifest
    assert '"release_status": "release"' in manifest
