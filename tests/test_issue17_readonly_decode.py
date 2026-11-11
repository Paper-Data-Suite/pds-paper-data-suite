"""Suite #17 Slice 2: selected-source scanning is bounded and never dispatches."""

from __future__ import annotations

import hashlib
import struct
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecodeLimits,
    DecoderBackendUnavailable,
    decode_with_optional_backends,
    observe_selected_sources,
)

GOOD = "PDS2|m=quillan|c=english12_p4|w=memoir|r=rt_1123456789abcdef0123456789abcdef"
OTHER = "PDS2|m=concord|c=english11_p3|w=demeter|r=rt_2123456789abcdef0123456789abcdef"


def _parse(value: str) -> SimpleNamespace:
    if not value.startswith("PDS2|"):
        raise ValueError("invalid QR: sensitive route should never be displayed")
    module = value.split("|m=", 1)[1].split("|", 1)[0]
    return SimpleNamespace(module_id=module)


def _png_bytes() -> bytes:
    """Create a valid 8x8 white PNG without optional image dependencies."""
    width = height = 8

    def chunk(kind: bytes, payload: bytes) -> bytes:
        content = kind + payload
        return (
            struct.pack(">I", len(payload))
            + content
            + struct.pack(">I", zlib.crc32(content))
        )

    rgb_rows = (b"\x00" + b"\xff\xff\xff" * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rgb_rows))
        + chunk(b"IEND", b"")
    )


def test_stdlib_png_fixture_has_valid_rgb_pixels_and_crc() -> None:
    """Core-only CI must not need Pillow merely to create input bytes."""
    image = _png_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(image):
        length = struct.unpack_from(">I", image, offset)[0]
        kind = image[offset + 4:offset + 8]
        payload = image[offset + 8:offset + 8 + length]
        actual_crc = struct.unpack_from(">I", image, offset + 8 + length)[0]
        assert actual_crc == zlib.crc32(kind + payload)
        chunks.append((kind, payload))
        offset += 12 + length
    assert offset == len(image)
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    assert chunks[0][1] == struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    assert zlib.decompress(chunks[1][1]) == (
        b"\x00" + b"\xff\xff\xff" * 8
    ) * 8


def _source(tmp_path: Path, *, suffix: str = ".png", data: bytes | None = None) -> Path:
    selected = tmp_path / ("selected" + suffix)
    selected.write_bytes(_png_bytes() if data is None else data)
    return selected


def _fake_decoder(
    pages: tuple[DecodedPage, ...], calls: list[tuple[bytes, str]] | None = None
):
    def decode(data: bytes, fmt: str, _: DecodeLimits) -> tuple[DecodedPage, ...]:
        if calls is not None:
            calls.append((data, fmt))
        return pages
    return decode


def test_source_preview_preserves_page_order_hash_and_no_writes(tmp_path: Path) -> None:
    original = _png_bytes()
    selected = _source(tmp_path, data=original)
    before = selected.stat()
    rows = observe_selected_sources(
        (selected,),
        decoder=_fake_decoder((
            DecodedPage((GOOD,)),
            DecodedPage(),
            DecodedPage((GOOD, GOOD)),
            DecodedPage((GOOD, OTHER)),
            DecodedPage(("PDS1|fake",)),
            DecodedPage(failed=True),
        )),
        parse_payload=_parse,
    )
    assert len(rows) == 1
    assert rows[0].status == "observed"
    assert rows[0].sha256_advisory == hashlib.sha256(original).hexdigest()
    actual = [(p.page_number, p.status, p.candidate_module_id) for p in rows[0].pages]
    assert actual == [
        (1, "candidate_unverified", "quillan"),
        (2, "missing_qr", None),
        (3, "candidate_unverified", "quillan"),
        (4, "ambiguous_qr", None),
        (5, "invalid_or_foreign_qr", None),
        (6, "page_decode_failed", None),
    ]
    assert selected.read_bytes() == original
    after = selected.stat()
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)
    assert sorted(p.name for p in tmp_path.iterdir()) == [selected.name]
    assert GOOD not in repr(rows)
    assert str(selected) not in repr(rows)


def test_selected_source_list_has_stable_order(tmp_path: Path) -> None:
    first = _source(tmp_path)
    second = tmp_path / "second.jpg"
    second.write_bytes(b"\xff\xd8\xffnot-real-jpeg")
    calls: list[tuple[bytes, str]] = []
    pages = (DecodedPage((OTHER,)),)
    rows = observe_selected_sources(
        (first, second),
        decoder=_fake_decoder(pages, calls),
        parse_payload=_parse,
    )
    assert [(s.source_number, s.status) for s in rows] == [
        (1, "observed"), (2, "observed")
    ]
    assert [s.pages[0].candidate_module_id for s in rows] == ["concord", "concord"]
    assert [x[1] for x in calls] == ["png", "jpeg"]


def test_unsupported_and_mismatched_magic_do_not_call_decoder(tmp_path: Path) -> None:
    unsupported = _source(tmp_path, suffix=".txt", data=b"hello")
    mismatched = tmp_path / "wrong.pdf"
    mismatched.write_bytes(_png_bytes())
    calls: list[tuple[bytes, str]] = []
    result = observe_selected_sources(
        (unsupported, mismatched),
        decoder=_fake_decoder((DecodedPage(),), calls),
        parse_payload=_parse,
    )
    assert [x.status for x in result] == ["unsupported_format", "source_decode_failed"]
    assert calls == []


def test_missing_directory_and_symlink_are_unavailable(tmp_path: Path) -> None:
    actual = _source(tmp_path)
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")
    result = observe_selected_sources(
        (tmp_path / "missing.png", tmp_path, link),
        decoder=_fake_decoder((DecodedPage(),)),
        parse_payload=_parse,
    )
    assert all(row.status == "source_unavailable" for row in result)


def test_resource_limits_fail_before_decoder(tmp_path: Path) -> None:
    source = _source(tmp_path)
    calls: list[tuple[bytes, str]] = []
    row = observe_selected_sources(
        (source,), limits=DecodeLimits(max_source_bytes=4),
        decoder=_fake_decoder((DecodedPage(),), calls),
        parse_payload=_parse,
    )[0]
    assert row.status == "resource_limit"
    assert calls == []
    with pytest.raises(ValueError, match="selected source count"):
        observe_selected_sources((source,) * 17)
    with pytest.raises(ValueError, match="bounded"):
        DecodeLimits(max_pages=101)
    with pytest.raises(ValueError, match="pdf_scale"):
        DecodeLimits(pdf_scale=25.0)


def test_backend_unavailable_and_bad_decoder_output_are_not_success(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)

    def missing(_: bytes, __: str, ___: DecodeLimits) -> tuple[DecodedPage, ...]:
        raise DecoderBackendUnavailable("private data")

    assert observe_selected_sources((source,), decoder=missing)[0].status == (
        "backend_unavailable"
    )
    assert observe_selected_sources((source,), decoder=_fake_decoder(()))[0].status == (
        "resource_limit"
    )
    assert observe_selected_sources(
        (source,), decoder=_fake_decoder((DecodedPage(), DecodedPage())),
        limits=DecodeLimits(max_pages=1),
    )[0].status == "resource_limit"


def test_decoder_never_picks_one_of_conflicting_codes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    rows = observe_selected_sources(
        (source,),
        decoder=_fake_decoder((
            DecodedPage((GOOD, "PDS1|m=scoreform")),
            DecodedPage((GOOD,), truncated=True),
            DecodedPage((GOOD + "x" * 500,)),
        )),
        parse_payload=_parse,
    )
    assert [page.status for page in rows[0].pages] == [
        "ambiguous_qr", "ambiguous_qr", "invalid_or_foreign_qr"
    ]


def test_sensitive_exception_text_cannot_leak_from_page_backend(tmp_path: Path) -> None:
    source = _source(tmp_path)

    def fail(_: bytes, __: str, ___: DecodeLimits) -> tuple[DecodedPage, ...]:
        raise RuntimeError("C:/private/grades/student_A")

    rows = observe_selected_sources((source,), decoder=fail)
    assert rows[0].status == "source_decode_failed"
    assert "private" not in repr(rows)


def test_no_dependency_or_provider_load_during_injected_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.returned_paper_readonly_decode as service

    selected = _source(tmp_path)
    called: list[str] = []

    def forbidden(name: str) -> object:
        called.append(name)
        raise AssertionError("No native backend/provider import allowed")

    monkeypatch.setattr(service, "import_module", forbidden)
    result = observe_selected_sources(
        (selected,), decoder=_fake_decoder((DecodedPage((GOOD,)),)),
        parse_payload=_parse,
    )
    assert result[0].pages[0].candidate_module_id == "quillan"
    assert not called


def test_decode_page_flags_validate_without_exposing_sensitive_text() -> None:
    page = DecodedPage((GOOD,))
    assert GOOD not in repr(page)
    with pytest.raises(ValueError):
        DecodedPage((GOOD,), failed=True)
    with pytest.raises(ValueError):
        DecodedPage((12,))  # type: ignore[arg-type]


def test_read_codes_is_qr_only_and_truncation_is_not_a_candidate() -> None:
    from paper_data_suite.returned_paper_readonly_decode import _read_codes

    class Reader:
        BarcodeFormat = SimpleNamespace(QRCode="QR_ONLY")

        @staticmethod
        def read_barcodes(image: object, *, formats: str) -> object:
            assert formats == "QR_ONLY"
            return [SimpleNamespace(text=GOOD)] * 3

    assert _read_codes(object(), DecodeLimits(), Reader()).payloads == (GOOD,) * 3
    over = _read_codes(object(), DecodeLimits(max_codes_per_page=2), Reader())
    assert over.truncated


def test_default_png_backend_does_not_report_missing_if_qr_library_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.returned_paper_readonly_decode as service

    source = _source(tmp_path)
    original_import = service.import_module

    def missing(name: str) -> object:
        if name == "zxingcpp":
            raise ImportError("unavailable")
        return original_import(name)

    monkeypatch.setattr(service, "import_module", missing)
    rows = observe_selected_sources((source,), decoder=decode_with_optional_backends)
    assert rows[0].status == "backend_unavailable"


def test_actual_core_parser_when_installed(tmp_path: Path) -> None:
    pytest.importorskip("pds_core.pds2")
    source = _source(tmp_path)
    rows = observe_selected_sources(
        (source,), decoder=_fake_decoder((DecodedPage((GOOD,)),))
    )
    assert rows[0].pages[0].candidate_module_id == "quillan"


def test_real_png_and_multipage_pdf_qr_smoke_when_backends_available(
    tmp_path: Path,
) -> None:
    """Generated synthetic paper only; optional until exact native wheels qualify."""
    pytest.importorskip("zxingcpp")
    pdfium = pytest.importorskip("pypdfium2")
    qrcode = pytest.importorskip("qrcode")
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    qr = qrcode.make(GOOD).convert("RGB")
    png = tmp_path / "synthetic.png"
    qr.save(png)
    row = observe_selected_sources((png,))[0]
    assert row.status == "observed"
    assert row.pages[0].candidate_module_id == "quillan"

    buf = BytesIO()
    pdf = Canvas(buf, pagesize=(612, 792))
    pdf.drawImage(ImageReader(qr), 80, 350, width=400, height=400)
    pdf.showPage()
    pdf.drawString(100, 500, "Synthetic blank page (no QR)")
    pdf.showPage()
    pdf.save()
    pdf_path = tmp_path / "synthetic.pdf"
    pdf_path.write_bytes(buf.getvalue())
    rows = observe_selected_sources((pdf_path,))
    assert rows[0].status == "observed", pdfium.__version__
    assert [p.status for p in rows[0].pages] == [
        "candidate_unverified", "missing_qr"
    ]
    with Image.open(png) as img:
        assert img.size[0] > 0


def test_real_pdfium_page_renderer_with_injected_qr_reader() -> None:
    """Exercises actual PDFium/PIL resource handling without relying on zxing-cpp."""
    pytest.importorskip("pypdfium2")
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from reportlab.pdfgen.canvas import Canvas

    from paper_data_suite.returned_paper_readonly_decode import _pdf_pages

    pdf_bytes = BytesIO()
    canvas = Canvas(pdf_bytes, pagesize=(612, 792))
    canvas.drawString(40, 700, "Synthetic page A")
    canvas.showPage()
    canvas.drawString(40, 700, "Synthetic page B")
    canvas.showPage()
    canvas.save()

    class Reader:
        BarcodeFormat = SimpleNamespace(QRCode="QR_ONLY")

        @staticmethod
        def read_barcodes(image: object, *, formats: str) -> object:
            assert formats == "QR_ONLY"
            assert image.size[0] > 0  # type: ignore[attr-defined]
            return [SimpleNamespace(text=GOOD)]

    pages = _pdf_pages(pdf_bytes.getvalue(), DecodeLimits(), Reader())
    assert len(pages) == 2
    assert all(page.payloads == (GOOD,) for page in pages)
