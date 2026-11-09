"""Suite #17 Slice 2: bounded read-only PDF/image PDS2 QR observations.

This observes a source's physical pages without Core retention, module routing,
provider imports, workspace state, or persisted paper artifacts. Decoded strings
are transient, never retained in PagePreview or a public error/diagnostic.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import warnings
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Callable, Final, Literal, Protocol

from paper_data_suite.returned_paper_preview_contract import (
    PagePreview,
    SourcePreview,
)

SourceFormat = Literal["pdf", "png", "jpeg"]

_MAX_SOURCES: Final[int] = 16
_MAX_SOURCE_BYTES: Final[int] = 32 * 1024 * 1024
_MAX_PAGES: Final[int] = 100
_MAX_PIXELS: Final[int] = 16_000_000
_MAX_DIMENSION: Final[int] = 6000
_MAX_CODES_PER_PAGE: Final[int] = 12
_MAX_CODE_LENGTH: Final[int] = 512


@dataclass(frozen=True, slots=True)
class DecodeLimits:
    """Fail-closed ceilings; callers cannot raise beyond audited maxima."""

    max_sources: int = 8
    max_source_bytes: int = 24 * 1024 * 1024
    max_pages: int = 64
    max_pixels: int = 12_000_000
    max_dimension: int = 5000
    max_codes_per_page: int = 8
    max_code_length: int = 512
    pdf_scale: float = 2.0

    def __post_init__(self) -> None:
        bounds = (
            ("max_sources", self.max_sources, _MAX_SOURCES),
            ("max_source_bytes", self.max_source_bytes, _MAX_SOURCE_BYTES),
            ("max_pages", self.max_pages, _MAX_PAGES),
            ("max_pixels", self.max_pixels, _MAX_PIXELS),
            ("max_dimension", self.max_dimension, _MAX_DIMENSION),
            ("max_codes_per_page", self.max_codes_per_page, _MAX_CODES_PER_PAGE),
            ("max_code_length", self.max_code_length, _MAX_CODE_LENGTH),
        )
        for name, value, maximum in bounds:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be a bounded positive integer")
        if type(self.pdf_scale) is not float or not 0.5 <= self.pdf_scale <= 3.0:
            raise ValueError("pdf_scale must be a float between 0.5 and 3.0")


@dataclass(frozen=True, slots=True, repr=False)
class DecodedPage:
    """Internal transient QR strings; intentionally absent from repr/errors."""

    payloads: tuple[str, ...] = ()
    failed: bool = False
    truncated: bool = False

    def __post_init__(self) -> None:
        if type(self.payloads) is not tuple or any(
            type(value) is not str for value in self.payloads
        ):
            raise ValueError("decoded page payloads must be a tuple of strings")
        if type(self.failed) is not bool or type(self.truncated) is not bool:
            raise ValueError("decoded page flags must be boolean")
        if self.failed and (self.payloads or self.truncated):
            raise ValueError("failed page cannot claim decoded payloads")


class PageDecoder(Protocol):
    """Injection seam; implementation receives bounded source bytes, not paths."""

    def __call__(
        self, source: bytes, source_format: SourceFormat, limits: DecodeLimits, /
    ) -> tuple[DecodedPage, ...]: ...


class ParsedLocator(Protocol):
    """Only the actual Core RouteLocator's module ID is exposed to UI."""

    @property
    def module_id(self) -> str: ...


PayloadParser = Callable[[str], ParsedLocator]


class DecoderBackendUnavailable(RuntimeError):
    """An optional native/Python scanning dependency could not be loaded."""


class DecodeResourceLimit(RuntimeError):
    """Requested physical-page operation exceeds a non-negotiable bound."""


class DecodeSourceError(RuntimeError):
    """The supplied source is unreadable, corrupt, or unstable."""


class _SourceUnavailable(RuntimeError):
    pass


def _core_parse(payload: str) -> ParsedLocator:
    from pds_core.pds2 import parse_pds2_payload

    return parse_pds2_payload(payload)


def _source_format(path: Path, data: bytes) -> SourceFormat:
    extension = path.suffix.casefold()
    expected: dict[str, SourceFormat] = {
        ".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg",
    }
    if extension not in expected:
        raise ValueError("unsupported source extension")
    magic = (
        "pdf" if data.startswith(b"%PDF-") else
        "png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
        "jpeg" if data.startswith(b"\xff\xd8\xff") else None
    )
    if magic != expected[extension]:
        raise DecodeSourceError("source signature does not match extension")
    return expected[extension]


def _read_source(path: Path, limits: DecodeLimits) -> bytes:
    try:
        if ".." in path.parts:
            raise _SourceUnavailable("unsafe relative component")
        # Refuse links at every component, including a symlinked parent.
        for part in (path, *path.parents):
            if part.is_symlink():
                raise _SourceUnavailable("linked source")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise _SourceUnavailable("not a regular file")
        if before.st_size > limits.max_source_bytes:
            raise DecodeResourceLimit("source byte limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise _SourceUnavailable("source changed before opening")
            data = stream.read(limits.max_source_bytes + 1)
            after = os.fstat(stream.fileno())
            if len(data) > limits.max_source_bytes:
                raise DecodeResourceLimit("source byte limit")
            if (
                (opened.st_size, opened.st_mtime_ns, opened.st_ino)
                != (after.st_size, after.st_mtime_ns, after.st_ino)
                or len(data) != after.st_size
            ):
                raise DecodeSourceError("source changed while reading")
            return data
    except (OSError, ValueError) as error:
        raise _SourceUnavailable("source unavailable") from error


def _check_image_size(width: int, height: int, limits: DecodeLimits) -> None:
    if (
        width < 1 or height < 1
        or width > limits.max_dimension or height > limits.max_dimension
        or width * height > limits.max_pixels
    ):
        raise DecodeResourceLimit("page pixel/dimension limit")


def _read_codes(image: object, limits: DecodeLimits, reader: object) -> DecodedPage:
    try:
        # Explicit QR-only format: barcodes are not equivalent to PDS2 QR codes.
        qr = reader.BarcodeFormat.QRCode  # type: ignore[attr-defined]
        results = reader.read_barcodes(image, formats=qr)  # type: ignore[attr-defined]
        values: list[str] = []
        for result in results:
            value = result.text
            if type(value) is not str:
                raise DecodeSourceError("QR decoder returned a non-text value")
            if len(values) >= limits.max_codes_per_page:
                return DecodedPage(tuple(values), truncated=True)
            values.append(value[: limits.max_code_length + 1])
        return DecodedPage(tuple(values))
    except Exception:
        # Decoder failures are page-local; no raw native error reaches the UI.
        return DecodedPage(failed=True)


def _image_pages(
    source: bytes, limits: DecodeLimits, reader: object
) -> tuple[DecodedPage, ...]:
    image_lib = import_module("PIL.Image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", image_lib.DecompressionBombWarning)
            with image_lib.open(BytesIO(source)) as opened:
                if getattr(opened, "n_frames", 1) != 1:
                    raise DecodeSourceError("multiframe image unsupported")
                _check_image_size(opened.size[0], opened.size[1], limits)
                with opened.convert("RGB") as image:
                    return (_read_codes(image, limits, reader),)
    except DecodeResourceLimit:
        raise
    except Exception as error:
        raise DecodeSourceError("image decode failed") from error


def _pdf_pages(
    source: bytes, limits: DecodeLimits, reader: object
) -> tuple[DecodedPage, ...]:
    pdfium = import_module("pypdfium2")
    pages: list[DecodedPage] = []
    try:
        # Use bounded in-memory bytes; the native decoder never receives the
        # teacher's original file path or a Core retained-source path.
        document = pdfium.PdfDocument(source)
        try:
            count = len(document)
            if not 1 <= count <= limits.max_pages:
                raise DecodeResourceLimit("PDF page count limit")
            for index in range(count):
                page = None
                bitmap = None
                image = None
                try:
                    page = document[index]
                    width, height = page.get_size()
                    if not (math.isfinite(width) and math.isfinite(height)):
                        raise DecodeResourceLimit("non-finite PDF dimensions")
                    _check_image_size(
                        math.ceil(width * limits.pdf_scale),
                        math.ceil(height * limits.pdf_scale),
                        limits,
                    )
                    bitmap = page.render(scale=limits.pdf_scale)
                    image = bitmap.to_pil()
                    _check_image_size(image.size[0], image.size[1], limits)
                    pages.append(_read_codes(image, limits, reader))
                except DecodeResourceLimit:
                    raise
                except Exception:
                    pages.append(DecodedPage(failed=True))
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    if page is not None:
                        page.close()
        finally:
            document.close()
    except DecodeResourceLimit:
        raise
    except Exception as error:
        raise DecodeSourceError("PDF decode failed") from error
    return tuple(pages)


def decode_with_optional_backends(
    source: bytes, source_format: SourceFormat, limits: DecodeLimits, /
) -> tuple[DecodedPage, ...]:
    """Lazy optional Pillow/PDFium/zxing-cpp decoding, no new dependencies."""
    try:
        reader = import_module("zxingcpp")
        import_module("PIL.Image")
        if source_format == "pdf":
            import_module("pypdfium2")
    except ImportError as error:
        raise DecoderBackendUnavailable(
            "scan decoder dependency unavailable"
        ) from error
    if source_format == "pdf":
        return _pdf_pages(source, limits, reader)
    return _image_pages(source, limits, reader)


def _observe_page(
    number: int, observation: DecodedPage, limits: DecodeLimits,
    parser: PayloadParser,
) -> PagePreview:
    if observation.failed:
        return PagePreview(number, "page_decode_failed")
    if observation.truncated or len(observation.payloads) > limits.max_codes_per_page:
        return PagePreview(number, "ambiguous_qr")
    unique = tuple(dict.fromkeys(observation.payloads))
    if len(unique) == 0:
        # No decoded QR is not proof that a visibly damaged QR is absent.
        return PagePreview(number, "missing_qr")
    if len(unique) > 1:
        return PagePreview(number, "ambiguous_qr")
    try:
        text = unique[0]
        if len(text) > limits.max_code_length:
            return PagePreview(number, "invalid_or_foreign_qr")
        locator = parser(text)
        return PagePreview(number, "candidate_unverified", locator.module_id)
    except (TypeError, ValueError, AttributeError):
        return PagePreview(number, "invalid_or_foreign_qr")


def observe_selected_sources(
    sources: tuple[str | Path, ...],
    *,
    limits: DecodeLimits = DecodeLimits(),
    decoder: PageDecoder = decode_with_optional_backends,
    parse_payload: PayloadParser = _core_parse,
) -> tuple[SourcePreview, ...]:
    """Return v1 SourcePreview rows without any reads outside selected sources.

    Not a durable custody record. The caller supplies explicit selected paths;
    no inbox walking, producer execution, workspace/scan file creation or writes.
    """
    if type(sources) is not tuple or len(sources) > limits.max_sources:
        raise ValueError("explicit selected source count exceeds the limit")
    found: list[SourcePreview] = []
    for number, raw in enumerate(sources, start=1):
        if not isinstance(raw, (Path, str)) or not str(raw):
            raise ValueError("selected source must be a nonempty file path")
        path = Path(raw)
        status: Literal[
            "source_unavailable", "unsupported_format", "resource_limit",
            "backend_unavailable", "source_decode_failed",
        ]
        try:
            data = _read_source(path, limits)
            fmt = _source_format(path, data)
            page_data = decoder(data, fmt, limits)
            if (
                type(page_data) is not tuple
                or not 1 <= len(page_data) <= limits.max_pages
                or any(not isinstance(page, DecodedPage) for page in page_data)
            ):
                raise DecodeResourceLimit("invalid decoder page count")
            pages = tuple(
                _observe_page(idx, item, limits, parse_payload)
                for idx, item in enumerate(page_data, start=1)
            )
            found.append(SourcePreview(
                number, "observed", pages,
                hashlib.sha256(data).hexdigest(),
            ))
            continue
        except _SourceUnavailable:
            status = "source_unavailable"
        except ValueError:
            # _source_format signals unsupported extension only.
            status = "unsupported_format"
        except DecodeResourceLimit:
            status = "resource_limit"
        except DecoderBackendUnavailable:
            status = "backend_unavailable"
        except (DecodeSourceError, OSError, RuntimeError):
            status = "source_decode_failed"
        found.append(SourcePreview(number, status))
    return tuple(found)


__all__ = [
    "DecodeLimits", "DecodedPage", "DecoderBackendUnavailable",
    "DecodeResourceLimit", "DecodeSourceError", "decode_with_optional_backends",
    "observe_selected_sources",
]
