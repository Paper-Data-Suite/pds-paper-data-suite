"""Suite #17 Slice 5: synthetic native inputs and strict offline wheel gates."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import issue17_slice5_native_acceptance as native
from scripts import issue17_slice5_wheel_audit as wheels


def _fake_wheel(path: Path, spec: wheels.WheelSpec, *, wrong: str = "") -> str:
    metadata = (
        f"Metadata-Version: 2.3\nName: {spec.distribution}\n"
        f"Version: {spec.version}\n"
    )
    if spec.distribution == "pds-concord":
        metadata += "Requires-Dist: pypdfium2>=4.30,<5\n"
    elif spec.distribution == "pds-vitrine":
        metadata += 'Requires-Dist: pypdfium2>=5.13,<6; extra == "paper"\n'
    entry_text = "[paper_data_suite.modules]\n"
    if spec.routing_name:
        target = spec.routing_target if wrong != "target" else "foreign:wrong"
        entry_text += f"{spec.routing_name} = {target}\n"
    with zipfile.ZipFile(path, "w") as archive:
        folder = f"{spec.filename.removesuffix('-py3-none-any.whl')}.dist-info"
        archive.writestr(f"{folder}/METADATA", metadata)
        archive.writestr(f"{folder}/entry_points.txt", entry_text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_wheelhouse(
    tmp_path: Path, *, wrong: str = ""
) -> tuple[wheels.WheelSpec, ...]:
    replacements = []
    for original in wheels.WHEELS:
        digest = _fake_wheel(
            tmp_path / original.filename, original,
            wrong=wrong if original.distribution == "scoreform" else "",
        )
        replacements.append(replace(original, sha256=digest))
    return tuple(replacements)


def test_exact_release_manifest_is_frozen_and_no_publisher_claims() -> None:
    assert [row.distribution for row in wheels.WHEELS] == [
        "pds-core", "scoreform", "quillan", "pds-concord", "pds-vitrine",
    ]
    assert len({row.sha256 for row in wheels.WHEELS}) == 5
    assert all(len(row.sha256) == 64 for row in wheels.WHEELS)


def test_offline_metadata_audit_reports_conflict_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wheels, "WHEELS", _fake_wheelhouse(tmp_path))
    result = wheels.audit_wheelhouse(tmp_path)
    assert result["wheel_count"] == 5
    assert result["combined_paper_wheel_installation_qualified"] is False
    assert result["shared_pdfium_dependency_resolution"] == "blocked_by_concord_170"
    assert result["provider_execution_performed"] is False
    assert result["publisher_signature_verified"] is False
    assert len(result["wheels"]) == 5


def test_offline_wheel_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wheels, "WHEELS", _fake_wheelhouse(tmp_path))
    target = tmp_path / wheels.WHEELS[1].filename
    target.write_bytes(target.read_bytes() + b"unexpected")
    with pytest.raises(wheels.WheelAuditError, match="SHA-256 mismatch"):
        wheels.audit_wheelhouse(tmp_path)


def test_wrong_routing_entry_point_is_not_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wheels, "WHEELS", _fake_wheelhouse(tmp_path, wrong="target"))
    with pytest.raises(wheels.WheelAuditError, match="routing declaration mismatch"):
        wheels.audit_wheelhouse(tmp_path)


def test_missing_official_wheel_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wheels, "WHEELS", _fake_wheelhouse(tmp_path))
    (tmp_path / wheels.WHEELS[2].filename).unlink()
    with pytest.raises(wheels.WheelAuditError, match="missing"):
        wheels.audit_wheelhouse(tmp_path)


def test_synthetic_mixed_pdf_and_image_files_have_exact_page_count(
    tmp_path: Path,
) -> None:
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("qrcode")
    pytest.importorskip("PIL")
    pdf, png, jpg = native._make_sources(tmp_path)
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert jpg.read_bytes().startswith(b"\xff\xd8\xff")
    document = pdfium.PdfDocument(pdf.read_bytes())
    try:
        assert len(document) == len(native.EXPECTED_PDF) == 9
    finally:
        document.close()
    assert {path.name for path in tmp_path.iterdir()} == {
        "synthetic_mixed.pdf", "synthetic_single.png", "synthetic_single.jpg",
    }


def test_native_expectations_include_legacy_ambiguous_and_absent() -> None:
    assert [status for status, _ in native.EXPECTED_PDF][-5:] == [
        "invalid_or_foreign_qr", "ambiguous_qr", "missing_qr",
        "candidate_unverified", "candidate_unverified",
    ]
    assert native.EXPECTED_PDF[-1][1] == "portia"
