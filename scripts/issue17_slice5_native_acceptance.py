"""Suite #17: actual offline synthetic mixed-PDF/PNG/JPEG QR acceptance.

Run only in a disposable native-scanner environment with the exact published
Core wheel. No student papers, active workspace, producer handlers or custody.
A decoded PDS2 locator remains only a *candidate*, never processing authority.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final

from packaging.version import Version

from paper_data_suite.returned_paper_readonly_decode import observe_selected_sources

PAYLOADS: Final[tuple[str, ...]] = (
    "PDS2|m=scoreform|c=class_a|w=quiz|r=rt_0123456789abcdef0123456789abcdef",
    "PDS2|m=quillan|c=class_a|w=essay|r=rt_1123456789abcdef0123456789abcdef",
    "PDS2|m=concord|c=class_a|w=activity|r=rt_2123456789abcdef0123456789abcdef",
    "PDS2|m=vitrine|c=class_a|w=portfolio|r=rt_3123456789abcdef0123456789abcdef",
    "PDS1|m=scoreform|c=class_a|w=legacy|r=rt_0123456789abcdef",
    "PDS2|m=portia|c=class_a|w=event|r=rt_4123456789abcdef0123456789abcdef",
)
EXPECTED_PDF: Final[tuple[tuple[str, str | None], ...]] = (
    ("candidate_unverified", "scoreform"),
    ("candidate_unverified", "quillan"),
    ("candidate_unverified", "concord"),
    ("candidate_unverified", "vitrine"),
    ("invalid_or_foreign_qr", None),
    ("ambiguous_qr", None),
    ("missing_qr", None),
    ("candidate_unverified", "quillan"),
    ("candidate_unverified", "portia"),
)


class NativeAcceptanceError(RuntimeError):
    """The genuine native scan path could not satisfy a synthetic acceptance case."""


def _version(name: str, minimum: str, maximum: str) -> str:
    value = importlib.metadata.version(name)
    if not Version(minimum) <= Version(value) < Version(maximum):
        raise NativeAcceptanceError("native scanner dependency outside qualified range")
    return value


def _qr(payload: str) -> Any:
    qrcode = import_module("qrcode")
    image_lib = import_module("PIL.Image")

    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    code.add_data(payload)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    pil = image.convert("RGB")
    try:
        return pil.resize((380, 380), resample=image_lib.Resampling.NEAREST)
    finally:
        pil.close()


def _paper(*payloads: str) -> Any:
    image_lib = import_module("PIL.Image")
    paper = image_lib.new("RGB", (900, 1100), "white")
    for index, payload in enumerate(payloads):
        if index >= 2:
            raise NativeAcceptanceError("synthetic page exceeds QR bound")
        tile = _qr(payload)
        try:
            # Two codes on a page intentionally force ambiguity or deduplication.
            paper.paste(tile, (50 + index * 450, 260))
        finally:
            tile.close()
    return paper


def _make_sources(folder: Path) -> tuple[Path, Path, Path]:
    pages = [
        _paper(PAYLOADS[0]),
        _paper(PAYLOADS[1]),
        _paper(PAYLOADS[2]),
        _paper(PAYLOADS[3]),
        _paper(PAYLOADS[4]),
        _paper(PAYLOADS[0], PAYLOADS[1]),
        _paper(),
        _paper(PAYLOADS[1], PAYLOADS[1]),
        _paper(PAYLOADS[5]),
    ]
    pdf = folder / "synthetic_mixed.pdf"
    png = folder / "synthetic_single.png"
    jpg = folder / "synthetic_single.jpg"
    try:
        pages[0].save(
            pdf, "PDF", resolution=144.0, save_all=True,
            append_images=pages[1:],
        )
    except (OSError, ValueError) as error:
        raise NativeAcceptanceError("synthetic PDF generation unavailable") from error
    finally:
        for page in pages:
            page.close()
    with _paper(PAYLOADS[0]) as page:
        page.save(png, "PNG")
    with _paper(PAYLOADS[1]) as page:
        page.save(jpg, "JPEG", quality=95, subsampling=0)
    return pdf, png, jpg


def _snapshot(paths: tuple[Path, ...]) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (hashlib.sha256(path.read_bytes()).hexdigest(),
         path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    )


def run_native_acceptance() -> dict[str, object]:
    """Test actual PDFium + zxing-cpp + Core parsing on disposable QR fixtures."""
    import_module("pypdfium2")
    import_module("zxingcpp")
    from pds_core.pds2 import parse_pds2_payload

    core_version = _version("pds-core", "0.6.6", "0.6.7")
    pdfium_version = _version("pypdfium2", "5.13", "6")
    qr_version = _version("zxing-cpp", "3.1.1", "4")
    pillow_version = _version("Pillow", "11", "13")
    for payload in (PAYLOADS[0], PAYLOADS[1], PAYLOADS[2], PAYLOADS[3], PAYLOADS[5]):
        parse_pds2_payload(payload)
    with TemporaryDirectory(prefix="suite17_synthetic_scans_") as temp:
        root = Path(temp)
        selected = _make_sources(root)
        workspace = root / "empty_workspace"
        workspace.mkdir()
        sentinel = workspace / "sentinel.txt"
        sentinel.write_text("no paper processing permitted\n", encoding="utf-8")
        before = _snapshot(selected + (sentinel,))
        files_before = sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*")
        )
        observations = observe_selected_sources(selected)
        after = _snapshot(selected + (sentinel,))
        files_after = sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*")
        )
        if before != after or files_before != files_after:
            raise NativeAcceptanceError("preview mutated source/workspace")
        if tuple(item.status for item in observations) != ("observed",) * 3:
            raise NativeAcceptanceError("PDF/image source observation incomplete")
        pdf_pages = observations[0].pages
        expected = EXPECTED_PDF
        actual = tuple((page.status, page.candidate_module_id) for page in pdf_pages)
        if actual != expected:
            raise NativeAcceptanceError("mixed-PDF physical page/QR results differ")
        if observations[1].pages[0].candidate_module_id != "scoreform":
            raise NativeAcceptanceError("PNG QR recognition mismatch")
        if observations[2].pages[0].candidate_module_id != "quillan":
            raise NativeAcceptanceError("JPEG QR recognition mismatch")
        for source in observations:
            if source.sha256_advisory is None or source.status != "observed":
                raise NativeAcceptanceError("missing source observation/fingerprint")
            if tuple(page.page_number for page in source.pages) != tuple(
                range(1, len(source.pages) + 1)
            ):
                raise NativeAcceptanceError("physical page numbering changed")
        if any(
            "PDS2|" in repr(source) or str(root) in repr(source)
            for source in observations
        ):
            raise NativeAcceptanceError("source observation leaked transient data")
    return {
        "schema_version": "1",
        "result": "native_synthetic_scan_passed",
        "core_version": core_version,
        "pdfium_version": pdfium_version,
        "zxing_cpp_version": qr_version,
        "pillow_version": pillow_version,
        "physical_pdf_pages": len(expected),
        "image_sources": 2,
        "candidate_pdf_pages": sum(x[0] == "candidate_unverified" for x in expected),
        "sources_and_workspace_unchanged": True,
        "official_producer_wheel_composition_qualified": False,
        "teacher_processing_performed": False,
        "input_data": "synthetic_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Suite #17 isolated native scan smoke")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_native_acceptance()
        args.evidence.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (Exception, KeyboardInterrupt):
        # Do not print native library errors or source paths into teacher logs.
        print("SUITE17_NATIVE_SCAN_NOT_QUALIFIED")
        return 1
    print("SUITE17_NATIVE_PDF_QR_SYNTHETIC_ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
